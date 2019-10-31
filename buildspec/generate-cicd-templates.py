#!/usr/bin/python
import boto3
import sys
import time
import os
import json
import generate_users_template
import pipeline_builder
from utils import read_file, write_file, get_policy_statements, add_policy_statements, consolidate_statements
from collections import OrderedDict
from botocore.exceptions import ClientError

# Variables
FILE_CONFIG_SCOPES = 'Config-Scopes'
FILE_CONFIG_ENVIRONMENTS = 'Config-Environments'
FILE_CONFIG_USERS = 'Config-Users'
FILE_TEMPLATE_USERS = 'Users'
FILE_TEMPLATE_SCOPE_PARENT = 'Scope-CICD-Parent'
FILE_TEMPLATE_SCOPE_CICD_CHILD = 'Scope-CICD-Child'
MASTERSCOPESTACK = 'cicd-master-scopes'
ENVIRONMENT = os.environ['Environment']

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

def get_parameters_of_child_stacks(master_stack_created):
    client_cloudformation = boto3.client('cloudformation')
    child_stack_parameters = {}
    if master_stack_created:
        # Get master infra stack resources
        resource_summaries = client_cloudformation.list_stack_resources(
            StackName=MASTERSCOPESTACK
        )['StackResourceSummaries']
        # Get existing child stack parameters
        # Loop through master infra stack resources
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

# Check if master stack exists
def master_stack_exists():
    client_cloudformation = boto3.client('cloudformation')
    exists = True
    try:
        client_cloudformation.describe_stacks(StackName=MASTERSCOPESTACK)
    except ClientError:
        # Obviously not if the parent stack doesn't even exist
        exists = False
    return exists

def are_all_environments_created_for_scope(scope, child_stack_parameters):
    all_envs_created = True
    scope_lower = scope.lower()
    # Determine AllEnvironmentsCreated value
    if scope_lower not in child_stack_parameters:
        all_envs_created = False
    if all_envs_created:
        all_envs_created = list(filter(lambda item: item['ParameterKey'] == 'AllEnvironmentsCreated', child_stack_parameters[scope_lower]))[0]['ParameterValue']
    return all_envs_created

def insert_pipeline_step_for_environment(env, env_value, scope_lower, name):
    env_lower = env.lower()
    pipeline_step = {
            "Name": env,
            "Actions": [
                {
                    "Fn::If": [
                        "SdlcCloudFormation",
                        {
                            "ActionTypeId":{
                                "Category":"Deploy",
                                "Owner":"AWS",
                                "Provider":"CloudFormation",
                                "Version":"1"
                            },
                            "Configuration":{
                                "ActionMode":"REPLACE_ON_FAILURE",
                                "Capabilities":"CAPABILITY_IAM,CAPABILITY_AUTO_EXPAND",
                                "RoleArn":{
                                    "Fn::Sub":"arn:aws:iam::" + env_value['AccountId'] + ":role/"+ env_lower + "-${MasterPipeline}-scopes-" + scope_lower + "-CloudFormationRole"
                                },
                                "StackName":{
                                    "Fn::Sub": env_lower + "-" + scope_lower + "-" + name
                                },
                                "TemplatePath": {
                                    "Fn::If": [
                                        "CicdCodeBuild",
                                        "BuildOutput::CloudFormation-SDLC.template",
                                        "SourceOutput::CloudFormation-SDLC.template"
                                    ]
                                },
                                "TemplateConfiguration":{
                                    "Fn::If":[
                                        "IncludeSdlcCfvars",
                                        {
                                            "Fn::If": [
                                                "CicdCodeBuild",
                                                "BuildOutput::cfvars/" + env + ".template",
                                                "SourceOutput::cfvars/" + env + ".template"
                                            ]
                                        },
                                        {
                                            "Ref":"AWS::NoValue"
                                        }
                                    ]
                                },
                                "ParameterOverrides":{
                                    "Fn::Join": [
                                        "",
                                        [
                                            "{",
                                            {
                                                "Fn::If": [
                                                    "CicdCodeBuild",
                                                    "\"S3BucketName\" : { \"Fn::GetArtifactAtt\" : [\"BuildOutput\", \"BucketName\"]}, \"S3ObjectKey\" : { \"Fn::GetArtifactAtt\" : [\"BuildOutput\", \"ObjectKey\"]},",
                                                    "\"S3BucketName\" : { \"Fn::GetArtifactAtt\" : [\"SourceOutput\", \"BucketName\"]}, \"S3ObjectKey\" : { \"Fn::GetArtifactAtt\" : [\"SourceOutput\", \"ObjectKey\"]},"
                                                ]
                                            },
                                            {
                                                "Fn::Sub": "\"KmsCmkArn\": \"${KmsCmkArn}\","
                                            },
                                            {
                                                "Fn::Sub": "\"Environment\": \"" + env_lower + "\","
                                            },
                                            {
                                                "Fn::Sub": "\"MasterPipeline\": \"${MasterPipeline}\","
                                            },
                                            {
                                                "Fn::Sub": "\"Scope\": \"" + scope_lower + "\","
                                            },
                                            {
                                                "Fn::Sub": "\"SubScope\": \"" + name + "\""
                                            },
                                            "}"
                                        ]
                                    ]
                                }
                            },
                            "Name": "DeployCloudFormation",
                            "InputArtifacts": [
                                {
                                    "Name": "SourceOutput"
                                },
                                {
                                    "Fn::If": [
                                        "CicdCodeBuild",
                                        {
                                            "Name": "BuildOutput"
                                        },
                                        {
                                            "Ref": "AWS::NoValue"
                                        }
                                    ]
                                }
                            ],
                            "RunOrder": 2,
                            "RoleArn": {
                                "Fn::Sub":"arn:aws:iam::" + env_value['AccountId'] + ":role/" + env_lower + "-${MasterPipeline}-scopes-" + scope_lower + "-CodePipelineRole"
                            }
                        },
                        {
                            "Ref": "AWS::NoValue"
                        }
                    ]
                },
                {
                    "Fn::If": [
                        "SdlcCodeBuild",
                        {
                            "ActionTypeId": {
                                "Category": "Build",
                                "Owner": "AWS",
                                "Provider": "CodeBuild",
                                "Version": "1"
                            },
                            "Configuration": {
                                "ProjectName": {
                                    "Fn::Sub": env_lower + "-" + scope_lower + "-" + name + "-CodeBuild"
                                },
                                "PrimarySource": {
                                    "Fn::If": [
                                        "CicdCodeBuild",
                                        "BuildOutput",
                                        "SourceOutput"
                                    ]  
                                }
                            },
                            "Name": "CodeBuildSdlc",
                            "InputArtifacts": [
                                {
                                    "Name": "SourceOutput"
                                },
                                {
                                    "Fn::If": [
                                        "CicdCodeBuild",
                                        {
                                            "Name": "BuildOutput"
                                        },
                                        {
                                            "Ref": "AWS::NoValue"
                                        }
                                    ]
                                }
                            ],
                            "RunOrder": 3,
                            "RoleArn": {
                                "Fn::Sub":"arn:aws:iam::" + env_value['AccountId'] + ":role/" + env_lower + "-${MasterPipeline}-scopes-" + scope_lower + "-CodeBuildRole"
                            }
                        },
                        {
                            "Ref": "AWS::NoValue"
                        }
                    ]
                }
            ]
        }
    return pipeline_step

def insert_childstack_into_parentstack(template_scope_parent, scope, all_envs_created):
    scope_lower = scope.lower()
    template_scope_parent['Resources'][scope_lower] = {
        "Type" : "AWS::CloudFormation::Stack",
        "Properties": {
            "Parameters": {
                "MasterPipeline": {
                    "Ref": "MasterPipeline"
                },
                "Environment": {
                    "Ref": "Environment"
                },
                "Scope": scope_lower,
                "AllEnvironmentsCreated": str(all_envs_created),
                "MasterS3BucketName": {
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
                "Fn::Sub": "https://s3.amazonaws.com/${S3BucketName}/generated-cicd-templates/" + FILE_TEMPLATE_SCOPE_CICD_CHILD + "-" + scope_lower + ".template"
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
                "Fn::Sub": "arn:aws:iam::${AWS::AccountId}:role/cicd-${MasterPipeline}-scopes-${Scope}-CodePipelineRole"
            }
        )
    if purpose == "Deploy" or purpose == "All":
        base_statement.append(
            {
                "Fn::Sub": "arn:aws:iam::${AWS::AccountId}:role/cicd-${MasterPipeline}-scopes-${Scope}-CloudFormationRole"
            }
        )
        base_statement.append(
            {
                "Fn::Sub": "arn:aws:iam::${AWS::AccountId}:role/cicd-${MasterPipeline}-scopes-${Scope}-CodeBuildRole"
            }
        )

    # CICD account is not optional
    # base_statement = [
    #     {
    #         "Fn::Sub": "arn:aws:iam::${AWS::AccountId}:role/cicd-${MasterPipeline}-scopes-${Scope}-CloudFormationRole"
    #     },
    #     {
    #         "Fn::Sub": "arn:aws:iam::${AWS::AccountId}:role/cicd-${MasterPipeline}-scopes-${Scope}-CodePipelineRole"
    #     },
    #     {
    #         "Fn::Sub": "arn:aws:iam::${AWS::AccountId}:role/cicd-${MasterPipeline}-scopes-${Scope}-CodeBuildRole"
    #     }    
    #]

    # Loop Through SDLC Environments
    for env, env_value in environments.items():
        env_lower = env.lower()
        if purpose == "Pipeline" or purpose == "All":
            base_statement.append(
                {
                    "Fn::Sub": "arn:aws:iam::" + env_value['AccountId'] + ":role/" + env_lower + "-${MasterPipeline}-scopes-${Scope}-CodePipelineRole"
                }
            )
        if purpose == "Deploy" or purpose == "All":
            base_statement.append(
                {
                    "Fn::Sub": "arn:aws:iam::" + env_value['AccountId'] + ":role/" + env_lower + "-${MasterPipeline}-scopes-${Scope}-CloudFormationRole"
                }
            )
            base_statement.append(
                {
                    "Fn::Sub": "arn:aws:iam::" + env_value['AccountId'] + ":role/" + env_lower + "-${MasterPipeline}-scopes-${Scope}-CodeBuildRole"
                }
            )
    return base_statement

def generate_scoped_pipelines_template(environments, scope, scope_value):
    scope_lower = scope.lower()
    # Open child template to insert pipelines
    template_scope_child = read_file('templates/' + FILE_TEMPLATE_SCOPE_CICD_CHILD)

    template_scope_child = add_policy_statements(template_scope_child, scope, scope_value, 'Cicd')

    # Consolidate Policies
    template_scope_child['Resources']['IamPolicyService']['Properties']['PolicyDocument']['Statement'] = consolidate_statements(
        template_scope_child['Resources']['IamPolicyService']['Properties']['PolicyDocument']['Statement']
    )

    template_scope_child['Resources']['IamPolicyDeploy']['Properties']['PolicyDocument']['Statement'] = consolidate_statements(
        template_scope_child['Resources']['IamPolicyDeploy']['Properties']['PolicyDocument']['Statement']
    )

    template_scope_child['Resources']['IamPolicyPipeline']['Properties']['PolicyDocument']['Statement'] = consolidate_statements(
        template_scope_child['Resources']['IamPolicyPipeline']['Properties']['PolicyDocument']['Statement']
    )

    # Add cross account policies we created above
    template_scope_child['Resources']['IamPolicyPipeline']['Properties']['PolicyDocument']['Statement'].append(assume_role_statement)
    template_scope_child['Resources']['IamPolicyPipeline']['Properties']['PolicyDocument']['Statement'].append(pass_role_statement)
    template_scope_child['Resources']['IamPolicyDeploy']['Properties']['PolicyDocument']['Statement'].append(pass_role_statement)
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
    write_file('generated-cicd-templates/' + FILE_TEMPLATE_SCOPE_CICD_CHILD + '-' + scope_lower, template_scope_child)
    return

def generate_scoped_templates(environments):
    # Check if master stack exists
    master_stack_created = master_stack_exists()
    # Get parameters of child stacks
    # Obviously can't if the master stack doesn't even exist
    child_stack_parameters = get_parameters_of_child_stacks(master_stack_created)
    # Open files
    template_scope_parent = read_file('templates/' + FILE_TEMPLATE_SCOPE_PARENT)
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
    write_file('generated-cicd-templates/' + FILE_TEMPLATE_SCOPE_PARENT, template_scope_parent)

def main():
    # Open Environments File
    environments = read_file(FILE_CONFIG_ENVIRONMENTS)['SdlcAccounts']

    # Update cross account policy statements with environments
    update_statements_with_crossaccount_permissions(environments)

    # Generate scope templates
    generate_scoped_templates(environments)

    # Generate users template
    generate_users_template.generate_user_templates('generated-cicd-templates/', "Cicd")

if __name__ == "__main__":
    main()

    
