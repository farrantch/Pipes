#!/usr/bin/python
import boto3
import sys
import time
import os
import json
from utils import get_policy_statements, read_file, write_file, consolidate_statements
from collections import OrderedDict
from botocore.exceptions import ClientError

# Variables
FILE_CONFIG_SCOPES = 'Config-Scopes'
FILE_CONFIG_ENVIRONMENTS = 'Config-Environments'
FILE_CONFIG_USERS = 'Config-Users'
FILE_CONFIG_GROUPS = 'Config-Groups'
FILE_TEMPLATE_PIPELINE = 'Pipeline'
FILE_TEMPLATE_USERS = 'Users'
FILE_TEMPLATE_SCOPE_PARENT = 'Scope-CICD-Parent'
FILE_TEMPLATE_SCOPE_CICD_CHILD = 'Scope-CICD-Child'
MASTERSCOPESTACK = 'cicd-master-scopes'
ENVIRONMENT = os.environ['Environment']

def insert_user_into_userstack(template_users, user, user_policies, sso_account_id, scopes):
    user_lower = user.lower()
    policies = []
    for user_policy in user_policies:
        if len(user_policy['PolicyDocument']['Statement']) > 0:
            policies.append(user_policy)
    tags = [
        {
            "Key": "Environment",
            "Value": {
                "Fn::Sub": "${Environment}"
            }
        }
    ]
    for scope in scopes:
        tags.append(
            {
                "Key": "Scope/" + scope,
                "Value": True
            }
        )
    template_users['Resources']['IamRole' + user] = {
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
                "Policies" : policies,
                "RoleName" : {
                    "Fn::Sub": "${Environment}-" + user_lower
                },
                "Tags": tags
            }
        }
    return template_users

def add_policy_statements_to_user_policy(policies, user_statements, environment_type, scope=None):
    #scopes = read_file(FILE_CONFIG_SCOPES)
    # First, add scoped/* if exists
    if environment_type in policies:
        if 'scoped/*' in policies[environment_type]:
            for filename in os.listdir('policies/scoped'):
                temp = read_file('policies/scoped/' + filename.split('.')[0])
                # If scope provided, find & replace within policies
                replaced = json.loads(json.dumps(temp).replace('${Scope}', scope.lower())) if scope else json.loads(json.dumps(temp))
                if 'UserStatements' in replaced:
                    for statement in replaced['UserStatements']:
                        user_statements.append(statement)
        # Add rest of policies
        for policy in policies[environment_type]:
            if policy != 'scoped/*':
                # Don't re-add resource-scope policies if already added via wildcard
                if not policy.startswith('scoped/') or 'scoped/*' not in policies:
                    temp = read_file('policies/' + policy)
                    # If scope provided, find & replace within policies
                    replaced = json.loads(json.dumps(temp).replace('${Scope}', scope.lower())) if scope else json.loads(json.dumps(temp))
                    if 'UserStatements' in replaced:
                        for statement in replaced['UserStatements']:
                            if 'PolicyArn' in statement:
                                user_statements.extend(get_policy_statements(statement['PolicyArn']))
                            else:
                                user_statements.append(statement)

def add_scope_statements_to_user_policy(scope, user_statements, environment_type):
    # Read Scopes Files
    scopes = read_file(FILE_CONFIG_SCOPES)
    # Add policies from scopes file
    add_policy_statements_to_user_policy(scopes[scope]['Policies'], user_statements, environment_type, scope)

def generate_users_template(output_location, environment_type):
    # Open files
    users = read_file(FILE_CONFIG_USERS)
    groups = read_file(FILE_CONFIG_GROUPS)
    environments = read_file(FILE_CONFIG_ENVIRONMENTS)
    template_users = read_file('templates/' + FILE_TEMPLATE_USERS)
    # Loop through users
    for user, user_value in users.items():
        # Loop through scopes attached to user
        user_statements = []
        user_inline_policies = []
        scopes = []
        # Add User Scopes
        if 'Scopes' in user_value:
            for scope in user_value['Scopes']:
                scopes.append(scope)
                add_scope_statements_to_user_policy(scope, user_statements, environment_type)
        # Add Policies
        if 'Policies' in user_value:
            add_policy_statements_to_user_policy(user_value['Policies'], user_statements, environment_type)
        # Add Group Scopes
        if 'Groups' in user_value:
            for group in user_value['Groups']:
                if 'Scopes' in groups[group]:
                    for group_scope in groups[group]['Scopes']:
                        scopes.append(group_scope)
                        add_scope_statements_to_user_policy(group_scope, user_statements, environment_type)
                if 'Policies' in groups[group]:
                    #if environment_type in groups[group]['Policies']:
                    add_policy_statements_to_user_policy(groups[group]['Policies'], user_statements, environment_type)

        if 'Statements' in user_value:
            for statement in user_value['Statements']:
                user_statements.append(statement)
        if 'InlinePolicies' in user_value:
            for inline_policy in user_value['InlinePolicies']:
                user_inline_policies.append(inline_policy)
        # Minimize Statements
        user_statements_minimized = consolidate_statements(user_statements)
        # Insert user into Users stack
        user_inline_policies.append(
            {
                "PolicyDocument": {
                    "Version" : "2012-10-17",
                    "Statement": user_statements_minimized
                },
                "PolicyName": "PipesAutoGenerated"
            }
        )
        template_users = insert_user_into_userstack(template_users, user, user_inline_policies, environments['SsoAccount']['AccountId'], scopes)
    # Save file
    write_file(output_location + FILE_TEMPLATE_USERS, template_users)
    return

def main():
    # Generate users template
    generate_users_template('generated-cicd-templates/', "Sdlc")

if __name__ == "__main__":
    main()