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

def insert_user_into_userstack(template_users, user, user_policy, sso_account_id, scopes):
    user_lower = user.lower()
    policies = []
    if len(user_policy['PolicyDocument']['Statement']) > 0:
        policies = [ user_policy ]
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

def add_scope_statements_to_user_policy(scope, user_statements, environment_type):
    scopes = read_file(FILE_CONFIG_SCOPES)
    # First, add scoped/* if exists
    if environment_type in scopes[scope]['Policies']:
        if 'scoped/*' in scopes[scope]['Policies'][environment_type]:
            for filename in os.listdir('policies/scoped'):
                temp = read_file('policies/scoped/' + filename.split('.')[0])
                replaced = json.loads(json.dumps(temp).replace('${Scope}', scope.lower()))
                if 'UserStatements' in replaced:
                    for statement in replaced['UserStatements']:
                        user_statements.append(statement)
        # Add rest of policies
        for policy in scopes[scope]['Policies'][environment_type]:
            if policy != 'scoped/*':
                # Don't re-add resource-scope policies if already added via wildcard
                if not policy.startswith('scoped/') or 'scoped/*' not in scopes[scope]['Policies']:
                    temp = read_file('policies/' + policy)
                    replaced = json.loads(json.dumps(temp).replace('${Scope}', scope.lower()))
                    if 'UserStatements' in replaced:
                        for statement in replaced['UserStatements']:
                            if 'PolicyArn' in statement:
                                user_statements.extend(get_policy_statements(statement['PolicyArn']))
                            else:
                                user_statements.append(statement)

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
        scopes = []
        # Add User Scopes
        if 'Scopes' in user_value:
            for scope in user_value['Scopes']:
                scopes.append(scope)
                add_scope_statements_to_user_policy(scope, user_statements, environment_type)
        # Add Group Scopes
        if 'Groups' in user_value:
            for group in user_value['Groups']:
                if 'Scopes' in groups[group]:
                    for group_scope in groups[group]['Scopes']:
                        scopes.append(group_scope)
                        add_scope_statements_to_user_policy(group_scope, user_statements, environment_type)
        # Minimize Statements
        user_statements_minimized = consolidate_statements(user_statements)
        # Insert user into Users stack
        user_policy = {
            "PolicyDocument": {
                "Version" : "2012-10-17",
                "Statement": user_statements_minimized
            },
            "PolicyName": "PipesAutoGenerated"
        }
        template_users = insert_user_into_userstack(template_users, user, user_policy, environments['SsoAccount']['AccountId'], scopes)
    # Save file
    write_file(output_location + FILE_TEMPLATE_USERS, template_users)
    return

def main():
    # Generate users template
    generate_users_template('generated-cicd-templates/', "Sdlc")

if __name__ == "__main__":
    main()

    
