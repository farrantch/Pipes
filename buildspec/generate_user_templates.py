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

def insert_childstack_into_parentstack(template_users_parent, user, environment_type):
    environment_type_lower = environment_type.lower()
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
                "Fn::Sub": "https://s3.amazonaws.com/${S3BucketName}/generated-user-templates-" + environment_type_lower + "/" + FILE_TEMPLATE_USERS_CHILD + "-" + user + ".template"
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

def insert_user_into_userstack(template_user, user, user_value, user_statements):
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
                "Tags": tags
            }
        }
    template_user = insert_user_managed_policies(template_user, user_statements)
    return template_user

def add_policy_statements_to_user_policy(policies, user_statements, environment_type, scope=None):
    #scopes = read_file(FILE_CONFIG_SCOPES)
    # First, add scoped/* if exists
    if environment_type in policies:
        if 'scoped/*' in policies[environment_type]:
            for filename in os.listdir('policies/scoped'):
                temp = read_file('policies/scoped/' + filename.split('.')[0])
                # If scope provided, find & replace within policies
                scope_replaced = json.loads(json.dumps(temp).replace('${Scope}', scope)) if scope else json.loads(json.dumps(temp))
                scope_lower_replaced = json.loads(json.dumps(scope_replaced).replace('${ScopeLower}', scope.lower())) if scope else json.loads(json.dumps(scope_replaced))
                if 'UserStatements' in scope_lower_replaced:
                    for statement in scope_lower_replaced['UserStatements']:
                        user_statements.append(statement)
        # Add rest of policies
        for policy in policies[environment_type]:
            if policy != 'scoped/*':
                # Don't re-add resource-scope policies if already added via wildcard
                if not policy.startswith('scoped/') or 'scoped/*' not in policies:
                    temp = read_file('policies/' + policy)
                    # If scope provided, find & replace within policies
                    scope_replaced = json.loads(json.dumps(temp).replace('${Scope}', scope)) if scope else json.loads(json.dumps(temp))
                    scope_lower_replaced = json.loads(json.dumps(scope_replaced).replace('${ScopeLower}', scope.lower())) if scope else json.loads(json.dumps(scope_replaced))
                    if 'UserStatements' in scope_lower_replaced:
                        for statement in scope_lower_replaced['UserStatements']:
                            if 'PolicyArn' in statement:
                                user_statements.extend(get_policy_statements(statement['PolicyArn']))
                            else:
                                user_statements.append(statement)

def add_scope_statements_to_user_policy(scope, user_statements, environment_type):
    # Read Scopes Files
    scopes = read_file(FILE_CONFIG_SCOPES)
    # Add policies from scopes file
    add_policy_statements_to_user_policy(scopes[scope]['Policies'], user_statements, environment_type, scope)

def generate_user_statements(user, user_value, environment_type):
    groups = read_file(FILE_CONFIG_GROUPS)
    # Loop through scopes attached to user
    user_statements = []
    # Add User Scopes
    if 'Scopes' in user_value:
        for scope in user_value['Scopes']:
            add_scope_statements_to_user_policy(scope, user_statements, environment_type)
    # Add Policies
    if 'Policies' in user_value:
        add_policy_statements_to_user_policy(user_value['Policies'], user_statements, environment_type)
    # Add Group Scopes
    if 'Groups' in user_value:
        for group in user_value['Groups']:
            if 'Scopes' in groups[group]:
                for group_scope in groups[group]['Scopes']:
                    add_scope_statements_to_user_policy(group_scope, user_statements, environment_type)
            if 'Policies' in groups[group]:
                #if environment_type in groups[group]['Policies']:
                add_policy_statements_to_user_policy(groups[group]['Policies'], user_statements, environment_type)

    if 'Statements' in user_value:
        for statement in user_value['Statements']:
            user_statements.append(statement)
    # Minimize Statements
    user_statements_minimized = consolidate_statements(user_statements)
    return user_statements_minimized

def generate_user_template(user, user_value, environment_type, output_location):
    template_user_child = read_file('templates/' + FILE_TEMPLATE_USERS_CHILD)

    user_statements = generate_user_statements(user, user_value, environment_type)
    template_user_child = insert_user_into_userstack(template_user_child, user, user_value, user_statements)

    # Output User Child file
    write_file(output_location + FILE_TEMPLATE_USERS_CHILD + '-' + user, template_user_child)

def generate_user_templates(environment_type):
    # Open files
    users = read_file(FILE_CONFIG_USERS)
    template_users_parent = read_file('templates/' + FILE_TEMPLATE_USERS_PARENT)
    # Set output location 
    output_location = 'generated-user-templates-' + environment_type.lower() + '/'
    # Loop through users
    for user, user_value in users.items():
        # Insert Users child stack into Users parent stack
        insert_childstack_into_parentstack(template_users_parent, user, environment_type)
        # Generate user template
        generate_user_template(user, user_value, environment_type, output_location)
        
    # Save file
    write_file(output_location + FILE_TEMPLATE_USERS_PARENT, template_users_parent)
    return

def main():
    # Parse arguments
    parser = ArgumentParser()
    parser.add_argument("-et", "--environment_type", help="Choose environment type. Ex - 'Sdlc' or 'Cicd'")
    args = parser.parse_args()

    # Generate users template
    generate_user_templates(args.environment_type)

if __name__ == "__main__":
    main()