#!/usr/bin/python
import boto3
import sys
import time
import string
import os
import json
from utils import *
from collections import OrderedDict
from botocore.exceptions import ClientError
from argparse import ArgumentParser

def insert_childstack_into_parentstack(template_users_parent, user, environment):
    environment_lower = environment.lower()
    template_users_parent['Resources'][user] = {
        "Type" : "AWS::CloudFormation::Stack",
        "Properties": {
            "Parameters": {
                "MainPipeline": {
                    "Ref": "MainPipeline"
                },
                "Environment": {
                    "Ref": "Environment"
                },
                "User": user
            },
            "Tags" : [
                {
                    "Key": "Environment",
                    "Value": {
                        "Fn::Sub": "${Environment}"
                    }
                }
            ],
            "TemplateURL" : {
                "Fn::Sub": "https://s3.amazonaws.com/${S3BucketName}/builds/users/" + BUILD_NUM + "/" + environment + "/" + FILE_TEMPLATE_USERS_CHILD + "-" + user + ".template"
            }
        }
    }

def get_user_scopes(user_value):
    groups = read_file(FILE_CONFIG_GROUPS)
    # Add User Scopes
    scopes = []
    if 'Scopes' in user_value:
        for scope in user_value['Scopes']:
            scopes.append(scope)
    # Add Group Scopes
    if 'Groups' in user_value:
        for group in user_value['Groups']:
            if 'Scopes' in groups[group]:
                for group_scope in groups[group]['Scopes']:
                    scopes.append(group_scope)
    return scopes

def insert_user_managed_policies(template_user, user_statements):
    # BinPack user_statements into policies
    current_bin_num = 0
    current_bin_size = 0
    bins = [[]]
    # Loop through statements
    for statement in user_statements:
        # # Create new bin if needed
        # if len(bins) < current_bin_num + 1:
        #     bins.append([])
        # Get size of current statement
        statement_size = num_characters(statement)
        # If combined size less than max bin size, append statement, add to current size
        if statement_size + current_bin_size < 5900:
            bins[current_bin_num].append(statement)
            current_bin_size += statement_size
        else:
            bins.append([])
            current_bin_num += 1
            bins[current_bin_num].append(statement)
            current_bin_size = statement_size
    iteration = 1
    # Add policies to user template
    for b in bins:
        # Don't add empty statements
        if len(b) > 0:
            template_user['Resources']['IamManagedPolicy' + str(iteration)] = {
                "Type" : "AWS::IAM::ManagedPolicy",
                "Properties" : {
                    "PolicyDocument" : {
                        "Version":"2012-10-17",
                        "Statement" : b
                    },
                    "Roles" : [ { "Ref": "IamRole"} ]
                }
            }
        iteration += 1
    return template_user

def insert_user_into_userstack(template_user, user, user_value, user_statements, environment):
    groups = read_file(FILE_CONFIG_GROUPS)
    sso_account_id = read_file(FILE_CONFIG_ENVIRONMENTS)['SsoAccount']['AccountId']
    # Only include inline policies if they have statements
    inline_policies = []
    if 'PoliciesInline' in user_value:
        for user_inline_policy in user_value['PoliciesInline']:
            if len(user_inline_policy['PolicyDocument']['Statement']) > 0:
                inline_policies.append(user_inline_policy)

    # Add Tags to User Role
    tags = [
        {
            "Key": "Environment",
            "Value": {
                "Fn::Sub": "${Environment}"
            }
        }
    ]

    scopes = get_user_scopes(user_value)
    for scope in scopes:
        tags.append(
            {
                "Key": "Scope/" + scope,
                "Value": True
            }
        )

    template_user['Resources']['IamRole'] = {
            "Type" : "AWS::IAM::Role",
            "Properties" : {
                "AssumeRolePolicyDocument" : {
                    "Version" : "2012-10-17",
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Principal": {
                                "AWS": "arn:aws:iam::" + sso_account_id + ":root"
                            },
                            "Action": [ "sts:AssumeRole" ],
                            "Condition": {
                                "Bool": {
                                    "aws:MultiFactorAuthPresent": "true"
                                }
                            }
                        }
                    ]
                },
                "Policies" : inline_policies,
                "RoleName" : {
                    "Fn::Sub": "${Environment}-" + user
                },
                "ManagedPolicyArns": [],
                "Tags": tags
            }
        }
    template_user = insert_user_managed_policies(template_user, user_statements)
    
    # Add ManagedPolicies
    if 'ManagedPolicyArns' in user_value:
        if environment in user_value['ManagedPolicyArns']:
            for managedpolicy in user_value['ManagedPolicyArns'][environment]:
                template_user['Resources']['IamRole']['Properties']['ManagedPolicyArns'].append(managedpolicy)
    if 'Groups' in user_value:
        for group in user_value['Groups']:
            if 'ManagedPolicyArns' in groups[group]:
                if environment in groups[group]['ManagedPolicyArns']:
                    for managedpolicy in groups[group]['ManagedPolicyArns'][environment]:
                        template_user['Resources']['IamRole']['Properties']['ManagedPolicyArns'].append(managedpolicy)
    # Remove ManagedPolicyArn duplicates
    template_user['Resources']['IamRole']['Properties']['ManagedPolicyArns'] = list(set(template_user['Resources']['IamRole']['Properties']['ManagedPolicyArns']))
    return template_user

def add_policy_statements_to_user_policy(policies, user_statements, environment, scope=None):
    # If environment doesn't exist, set to default
    if environment not in policies:
        environment = 'Default'
    if environment in policies:
        # First, add scoped/* if exists
        if 'scoped/*' in policies[environment]:
            for filename in os.listdir('policies/scoped'):
                temp = read_file('policies/scoped/' + filename.split('.')[0])
                # If scope provided, find & replace within policies
                scope_replaced = json.loads(json.dumps(temp).replace('${Scope}', scope)) if scope else json.loads(json.dumps(temp))
                if 'UserStatements' in scope_replaced:
                    for statement in scope_replaced['UserStatements']:
                        user_statements.append(statement)
        # Add rest of policies
        for policy in policies[environment]:
            if policy != 'scoped/*':
                # Don't re-add resource-scope policies if already added via wildcard
                if not policy.startswith('scoped/') or 'scoped/*' not in policies:
                    # Parse everything before ':' to get file name
                    policyname_split = policy.split(':')
                    temp = read_file('policies/' + policyname_split[0])
                    # If contains alternative scope name, replace scope within file
                    if len(policyname_split) > 1:
                        scope = policyname_split[1]
                    # If scope provided, find & replace within policies
                    scope_replaced = json.loads(json.dumps(temp).replace('${Scope}', scope)) if scope else json.loads(json.dumps(temp))
                    if 'UserStatements' in scope_replaced:
                        for statement in scope_replaced['UserStatements']:
                            if 'PolicyArn' in statement:
                                user_statements.extend(get_policy_statements(statement['PolicyArn']))
                            else:
                                user_statements.append(statement)

def add_scope_statements_to_user_policy(scope, user_statements, environment):
    # Read Scopes Files
    scopes = read_file(FILE_CONFIG_SCOPES)
    # Add policies from scopes file
    if 'Policies' in scopes[scope]:
        add_policy_statements_to_user_policy(scopes[scope]['Policies'], user_statements, environment, scope)

def generate_user_statements(user, user_value, environment):
    groups = read_file(FILE_CONFIG_GROUPS)
    # Loop through scopes attached to user
    user_statements = []
    # Add User Scopes
    if 'Scopes' in user_value:
        for scope in user_value['Scopes']:
            add_scope_statements_to_user_policy(scope, user_statements, environment)
    # Add Policies
    if 'Policies' in user_value:
        add_policy_statements_to_user_policy(user_value['Policies'], user_statements, environment)
    # Add Group Scopes
    if 'Groups' in user_value:
        for group in user_value['Groups']:
            if 'Scopes' in groups[group]:
                for group_scope in groups[group]['Scopes']:
                    #if 'Policies' in group_scope:
                    add_scope_statements_to_user_policy(group_scope, user_statements, environment)
            if 'Policies' in groups[group]:
                #if environment in groups[group]['Policies']:
                add_policy_statements_to_user_policy(groups[group]['Policies'], user_statements, environment)
            # if 'ManagedPolicies' in groups[group]:
            #     if environment in groups[group]['ManagedPolicies']:
            #         for policymanaged in groups[group]['ManagedPolicies']:
            #             user_statements.append(policymanaged)

    if 'Statements' in user_value:
        for statement in user_value['Statements']:
            user_statements.append(statement)
    # Minimize Statements
    user_statements_minimized = consolidate_statements(user_statements)
    return user_statements_minimized

def generate_user_template(user, user_value, environment):
    template_user_child = read_file('templates/' + FILE_TEMPLATE_USERS_CHILD)
    # Generate User Policy
    user_statements = generate_user_statements(user, user_value, environment)
    template_user_child = insert_user_into_userstack(template_user_child, user, user_value, user_statements, environment)

    # Output User Child file
    write_file(OUTPUT_FOLDER + '/users/' + environment + '/' + FILE_TEMPLATE_USERS_CHILD + '-' + user, template_user_child)

def generate_user_templates(environment):
    # Open files
    users = read_file(FILE_CONFIG_USERS)
    template_users_parent = read_file('templates/' + FILE_TEMPLATE_USERS_PARENT)
    # Loop through users
    for user, user_value in users.items():
        # Insert Users child stack into Users parent stack
        insert_childstack_into_parentstack(template_users_parent, user, environment['Name'])
        # Generate user template
        generate_user_template(user, user_value, environment['Name'])
        
    # Save file
    write_file(OUTPUT_FOLDER + '/users/' + environment['Name'] + '/' + FILE_TEMPLATE_USERS_PARENT, template_users_parent)
    return

def main():
    # Loop through workload environments
    environments = read_file(FILE_CONFIG_ENVIRONMENTS)
    for env in environments['WorkloadAccounts']:
        # Generate users template
        generate_user_templates(env)

if __name__ == "__main__":
    main()