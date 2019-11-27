#!/usr/bin/python
import boto3
import sys
import time
import os
import json
import pipeline_builder
from utils import *
from collections import OrderedDict
from botocore.exceptions import ClientError

# Template Snippets
assume_role_statement = {
    "Fn::If": [
        "NotInitialCreation",
        {
            "Sid": "AllowAssumeEnvironmentRoles",
            "Effect": "Allow",
            "Action": [
                "sts:AssumeRole",
                
            ],
            "Resource": []
        },
        {
            "Ref": "AWS::NoValue"
        }
    ]
}
pass_role_statement = {
    "Fn::If": [
        "NotInitialCreation",
        {
            "Sid": "AllowPassEnvironmentRoles",
            "Effect": "Allow",
            "Action": [
                "iam:PassRole"
            ],
            "Resource": []
        },
        {
            "Ref": "AWS::NoValue"
        }
    ]
}
kms_key_statement = {
    "Fn::If": [
        "NotInitialCreation",
        {
            "Sid": "Allow other accounts to use the key.",
            "Effect": "Allow",
            "Principal": {
                "AWS": []
            },
            "Action": [
                "kms:DescribeKey",
                "kms:Encrypt",
                "kms:Decrypt",
                "kms:ReEncrypt",
                "kms:GenerateDataKey"
            ],
            "Resource": "*"
        },
        {
            "Ref": "AWS::NoValue"
        }
    ]
}
s3_bucket_statement = {
    "Fn::If": [
        "NotInitialCreation",
        {
            "Sid": "AccountsAllowedToS3Bucket",
            "Effect": "Allow",
            "Principal": {
                "AWS": []
            },
            "Action": [
                "s3:Get*",
                "s3:Put*",
                "s3:ListBucket"
            ],
            "Resource": [{
                    "Fn::Sub": [
                        "${S3BucketArn}/*",
                        {
                            "S3BucketArn": {
                                "Fn::GetAtt": [
                                    "S3Bucket",
                                    "Arn"
                                ]
                            }
                        }
                    ]
                },
                {
                    "Fn::GetAtt": [
                        "S3Bucket",
                        "Arn"
                    ]
                }
            ]
        },
        {
            "Ref": "AWS::NoValue"
        }
    ]
}

def get_parameters_of_child_stacks(main_stack_created):
    client_cloudformation = boto3.client('cloudformation')
    child_stack_parameters = {}
    if main_stack_created:
        # Get main infra stack resources
        resource_summaries = client_cloudformation.list_stack_resources(
            StackName=MAIN_PIPELINE_STACK
        )['StackResourceSummaries']
        # Get existing child stack parameters
        # Loop through main infra stack resources
        for rs in resource_summaries:
            # Only look for CloudFormation Stacks
            if rs['ResourceType'] == 'AWS::CloudFormation::Stack':
                # Get Stack parameters
                child_stack_parameters[rs['LogicalResourceId']] = client_cloudformation.describe_stacks(
                    StackName = rs['PhysicalResourceId']
                )['Stacks'][0]['Parameters']
    return child_stack_parameters

def update_statements_with_crossaccount_permissions(environments):
    # Generate base statement needed for cross-environment access.
    base_statement_all = generate_base_statement(environments, "All")
    base_statement_deploy = generate_base_statement(environments, "Deploy")
    base_statement_pipeline = generate_base_statement(environments, "Pipeline")
    # Insert base statement into larger statements
    assume_role_statement['Fn::If'][1]['Resource'] = base_statement_pipeline[:]
    pass_role_statement['Fn::If'][1]['Resource'] = base_statement_deploy[:]
    kms_key_statement['Fn::If'][1]['Principal']['AWS'] = base_statement_all[:]
    s3_bucket_statement['Fn::If'][1]['Principal']['AWS'] = base_statement_all[:]

# Check if main stack exists
def main_stack_exists():
    client_cloudformation = boto3.client('cloudformation')
    exists = True
    try:
        client_cloudformation.describe_stacks(StackName=MAIN_PIPELINE_STACK)
    except ClientError:
        # Obviously not if the parent stack doesn't even exist
        exists = False
    return exists

def are_all_environments_created_for_scope(scope, child_stack_parameters):
    all_envs_created = True
    # Determine AllEnvironmentsCreated value
    if scope not in child_stack_parameters:
        all_envs_created = False
    if all_envs_created:
        all_envs_created = list(filter(lambda item: item['ParameterKey'] == 'AllEnvironmentsCreated', child_stack_parameters[scope]))[0]['ParameterValue']
    return all_envs_created

def insert_childstack_into_parentstack(template_scope_parent, scope, all_envs_created):
    template_scope_parent['Resources'][scope] = {
        "Type" : "AWS::CloudFormation::Stack",
        "Properties": {
            "Parameters": {
                "MainPipeline": {
                    "Ref": "MainPipeline"
                },
                "Environment": {
                    "Ref": "Environment"
                },
                "Scope": scope,
                "AllEnvironmentsCreated": str(all_envs_created),
                "MainS3BucketName": {
                    "Fn::Sub": "${S3BucketName}"
                }
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
                "Fn::Sub": "https://s3.amazonaws.com/${S3BucketName}/generated-pipeline-templates/" + FILE_TEMPLATE_PIPELINES_CHILD + "-" + scope + ".template"
            }
        }
    }
    return template_scope_parent

# Generate base_statement policy used for cross-account access
def generate_base_statement(environments, purpose):
    # Purpose - All / Deploy / Pipeline
    base_statement = []
    if purpose == "Pipeline" or purpose == "All":
        base_statement.append(
            {
                "Fn::Sub": "arn:aws:iam::${AWS::AccountId}:role/cicd-${MainPipeline}-scopes-${Scope}-CodePipelineRole"
            }
        )
    if purpose == "Deploy" or purpose == "All":
        base_statement.append(
            {
                "Fn::Sub": "arn:aws:iam::${AWS::AccountId}:role/cicd-${MainPipeline}-scopes-${Scope}-CloudFormationRole"
            }
        )
        base_statement.append(
            {
                "Fn::Sub": "arn:aws:iam::${AWS::AccountId}:role/cicd-${MainPipeline}-scopes-${Scope}-CodeBuildRole"
            }
        )

    # Loop Through SDLC Environments
    for env, env_value in environments.items():
        env_lower = env.lower()
        if purpose == "Pipeline" or purpose == "All":
            base_statement.append(
                {
                    "Fn::Sub": "arn:aws:iam::" + env_value['AccountId'] + ":role/" + env_lower + "-${MainPipeline}-scopes-${Scope}-CodePipelineRole"
                }
            )
        if purpose == "Deploy" or purpose == "All":
            base_statement.append(
                {
                    "Fn::Sub": "arn:aws:iam::" + env_value['AccountId'] + ":role/" + env_lower + "-${MainPipeline}-scopes-${Scope}-CloudFormationRole"
                }
            )
            base_statement.append(
                {
                    "Fn::Sub": "arn:aws:iam::" + env_value['AccountId'] + ":role/" + env_lower + "-${MainPipeline}-scopes-${Scope}-CodeBuildRole"
                }
            )
    return base_statement

def generate_scoped_pipelines_template(environments, scope, scope_value):
    # Open child template to insert pipelines
    template_scope_child = read_file('templates/' + FILE_TEMPLATE_PIPELINES_CHILD)

    #template_scope_child = add_policy_statements(template_scope_child, scope, scope_value, 'Cicd')

    # Consolidate Policies
    # template_scope_child['Resources']['IamPolicyService']['Properties']['PolicyDocument']['Statement'] = consolidate_statements(
    #     template_scope_child['Resources']['IamPolicyService']['Properties']['PolicyDocument']['Statement']
    # )

    # template_scope_child['Resources']['IamPolicyDeploy']['Properties']['PolicyDocument']['Statement'] = consolidate_statements(
    #     template_scope_child['Resources']['IamPolicyDeploy']['Properties']['PolicyDocument']['Statement']
    # )

    template_scope_child['Resources']['IamPolicyPipeline']['Properties']['PolicyDocument']['Statement'] = consolidate_statements(
        template_scope_child['Resources']['IamPolicyPipeline']['Properties']['PolicyDocument']['Statement']
    )

    # Add cross account policies we created above
    template_scope_child['Resources']['IamPolicyPipeline']['Properties']['PolicyDocument']['Statement'].append(assume_role_statement)
    template_scope_child['Resources']['IamPolicyPipeline']['Properties']['PolicyDocument']['Statement'].append(pass_role_statement)
    #template_scope_child['Resources']['IamPolicyDeploy']['Properties']['PolicyDocument']['Statement'].append(pass_role_statement)
    template_scope_child['Resources']['KmsKey']['Properties']['KeyPolicy']['Statement'].append(kms_key_statement)
    template_scope_child['Resources']['S3BucketPolicy']['Properties']['PolicyDocument']['Statement'].append(s3_bucket_statement)

    # Loop through pipelines
    if 'Pipelines' in scope_value:
        for pipeline in scope_value['Pipelines']:
            # Insert PipelineStack into ChildStack
            #template_scope_child = insert_pipeline_into_childstack(environments, template_scope_child, pipeline, scope)
            template_scope_child['Resources']['CodePipeline' + pipeline['Name']] = (pipeline_builder
                .Pipeline(scope, environments, pipeline)
                    .Properties()
                        .Stages()
                            .Source()
                                .CodeCommit()
                                .Build()
                                .GitHub()
                                .Build()
                            .Build()
                            .Cicd()
                                .CicdCloudFormation()
                                .Build()
                                .CicdCodeBuild()
                                .Build()
                            .Build()
                            .Sdlc()
                                .Environments()
                                .Build()
                                .ManualApprovalPostDev()
                                .Build()
                                .ManualApprovalPreProd()
                                .Build()
                            .Build()
                        .Build()
                    .Build()
                .Build())
            # # Add PipelineStack Parameter Overrides
            # if 'Parameters' in pipeline:
            #     for po, po_value in pipeline['Parameters'].items():
            #         # Filter to parameters only applicable to CICD stack
            #         if po == 'SdlcCodeBuild' or po == 'SdlcCloudFormation' or po == 'CicdCodeBuild' or po == 'CicdCodeBuildImage' or po == 'IncludeCicdCfvars' or po =='IncludeSdlcCfvars' or po == 'SourceRepo':
            #             template_scope_child['Resources'][pipeline['Name']]['Properties']['Parameters'][po] = po_value
    # Save individual scoped child file
    write_file('generated-pipeline-templates/' + FILE_TEMPLATE_PIPELINES_CHILD + '-' + scope, template_scope_child)
    return

def generate_scoped_templates(environments):
    # Check if main stack exists
    main_stack_created = main_stack_exists()
    # Get parameters of child stacks
    # Obviously can't if the main stack doesn't even exist
    child_stack_parameters = get_parameters_of_child_stacks(main_stack_created)
    # Open files
    template_scope_parent = read_file('templates/' + FILE_TEMPLATE_PIPELINES_PARENT)
    scopes = read_file(FILE_CONFIG_SCOPES)
    # Loop through scopes
    for scope, scope_value in scopes.items():
        # Determine if all environments for this scope have been created
        all_envs_created = are_all_environments_created_for_scope(scope, child_stack_parameters)
        # Insert child stack into parent stack for CICD Scopes
        template_scope_parent = insert_childstack_into_parentstack(template_scope_parent, scope, all_envs_created)
        # Generate scoped pipelines template
        generate_scoped_pipelines_template(environments, scope, scope_value)
    # Save parent file
    write_file('generated-pipeline-templates/' + FILE_TEMPLATE_PIPELINES_PARENT, template_scope_parent)

def main():
    # Open Environments File
    environments = read_file(FILE_CONFIG_ENVIRONMENTS)['SdlcAccounts']

    # Update cross account policy statements with environments
    update_statements_with_crossaccount_permissions(environments)

    # Generate scope templates
    generate_scoped_templates(environments)

if __name__ == "__main__":
    main()