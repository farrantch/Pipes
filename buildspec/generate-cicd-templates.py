import boto3
import sys
import time
import os
import json
from collections import OrderedDict
from botocore.exceptions import ClientError

# Filenames
file_scopes = 'config/Scopes'
file_cicd_infra = 'infra-templates/CICD'
file_environments = 'config/Environments'
file_cicd_parent = 'Scope-CICD-Parent'
file_cicd_child = 'Scope-CICD-Child'

# Open Files
# Input Files
with open(file_scopes + '.template') as s_file:
    scopes = json.load(s_file)
with open(file_environments + '.template') as e_file:
    environments = json.load(e_file, object_pairs_hook=OrderedDict)
with open('scope-templates/' + file_cicd_parent + '.template') as cp_file:
    cicd_parent = json.load(cp_file)
with open(file_cicd_infra + '.template') as ci_file:
    cicd_infra = json.load(ci_file)
    
client = boto3.client('cloudformation')

#MASTERSCOPESTACK = os.environ['MASTERSCOPESTACK']
#ENVIRONMENT = os.environ['Environment']

MASTERSCOPESTACK = 'cicd-master-scopes'
ENVIRONMENT = 'cicd'

# Get master infra stack resources
aec = True
child_stack_parameters = {}
try:
    master_stack = client.describe_stacks(
        StackName=MASTERSCOPESTACK
    )
except ClientError:
    aec = False

if aec:
    resource_summaries = client.list_stack_resources(
        StackName=MASTERSCOPESTACK
    )['StackResourceSummaries']
    # Get existing child stack parameters
    # Loop through master infra stack resources
    for rs in resource_summaries:
        # Only look for CloudFormation Stacks
        if rs['ResourceType'] == 'AWS::CloudFormation::Stack':
            # Get Stack parameters
            child_stack_parameters[rs['LogicalResourceId']] = client.describe_stacks(
                StackName = rs['PhysicalResourceId']
            )['Stacks'][0]['Parameters']
    
# Add IamPolicyBaseline permissions to assume role into SDLC accounts
base_statement = []
assume_role_statement = {
    "Fn::If": [
        "NotInitialCreation",
        {
            "Sid": "AllowAssumeEnvironmentRoles",
            "Effect": "Allow",
            "Action": "sts:AssumeRole",
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
for env in environments:
    env_lower = env.lower()
    base_statement.append(
        {
            "Fn::Sub": "arn:aws:iam::${" + env + "Account}:role/" + env_lower + "-${MasterPipeline}-scopes-${Scope}-CloudFormationRole"
        }
    )
    base_statement.append(
        {
            "Fn::Sub": "arn:aws:iam::${" + env + "Account}:role/" + env_lower + "-${MasterPipeline}-scopes-${Scope}-CodePipelineRole"
        }
    )
    base_statement.append(
        {
            "Fn::Sub": "arn:aws:iam::${" + env + "Account}:role/" + env_lower + "-${MasterPipeline}-scopes-${Scope}-CodeBuildRole"
        }
    )

    # Insert env into child pipeline template
    pipeline_sdlc_env = {
        "Name": env,
        "Actions":[
            {
                "Fn::If": [
                    "SdlcCodeBuildPre",
                    {
                        "ActionTypeId": {
                        "Category": "Build",
                        "Owner": "AWS",
                        "Provider": "CodeBuild",
                        "Version": "1"
                        },
                        "Configuration": {
                            "ProjectName": {
                                "Fn::Sub": env_lower + "-${MasterPipeline}-scopes-${Scope}-${SubScope}-SdlcPre"
                            }
                        },
                        "Name": "CodeBuildSdlcPre",
                        "InputArtifacts": [
                        {
                            "Name": "SourceOutput"
                        }
                        ],
                        "RunOrder": 1,
                        "RoleArn": {
                            "Fn::Sub":"arn:aws:iam::${" + env + "Account}:role/" + env_lower + "-${MasterPipeline}-scopes-${Scope}-CodeBuildRole"
                        }
                    },
                    {
                        "Ref": "AWS::NoValue"
                    }
                ]
            },
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
                            "Capabilities":"CAPABILITY_IAM",
                            "RoleArn":{
                                "Fn::Sub":"arn:aws:iam::${" + env + "Account}:role/"+ env_lower + "-${MasterPipeline}-scopes-${Scope}-CloudFormationRole"
                            },
                            "StackName":{
                                "Fn::Sub": env_lower + "-${Scope}-${SubScope}"
                            },
                            "TemplatePath":"SourceOutput::CloudFormation.template",
                            "TemplateConfiguration":{
                                "Fn::If":[
                                    "IncludeEnvCfTemplateConfigs",
                                    "SourceOutput::cfvars/" + env + ".template",
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
                                            "Fn::If":[
                                                "CfContainsLambda",
                                                "\"S3BucketName\" : { \"Fn::GetArtifactAtt\" : [\"SourceOutput\", \"BucketName\"]}, \"S3ObjectKey\" : { \"Fn::GetArtifactAtt\" : [\"SourceOutput\", \"ObjectKey\"]},",
                                                {
                                                    "Ref":"AWS::NoValue"
                                                }
                                            ]
                                        },
                                        {
                                            "Fn::Sub": "\"Environment\": \"" + env_lower + "\","
                                        },
                                        {
                                            "Fn::Sub": "\"MasterPipeline\": \"${MasterPipeline}\","
                                        },
                                        {
                                            "Fn::Sub": "\"Scope\": \"${Scope}\""
                                        },
                                        "}"
                                    ]
                                ]
                            }
                        },
                        "Name": "DeployCloudFormation",
                        "InputArtifacts": [
                            {
                                "Name":"SourceOutput"
                            }
                        ],
                        "RunOrder": 2,
                        "RoleArn": {
                            "Fn::Sub":"arn:aws:iam::${" + env + "Account}:role/" + env_lower + "-${MasterPipeline}-scopes-${Scope}-CodePipelineRole"
                        }
                    },
                    {
                        "Ref": "AWS::NoValue"
                    }
                ]
            },
            {
                "Fn::If": [
                    "SdlcCodeBuildPost",
                    {
                        "ActionTypeId": {
                        "Category": "Build",
                        "Owner": "AWS",
                        "Provider": "CodeBuild",
                        "Version": "1"
                        },
                        "Configuration": {
                        "ProjectName": {
                            "Fn::Sub": env_lower + "-${MasterPipeline}-scopes-${Scope}-${SubScope}-SdlcPost"
                        }
                        },
                        "Name": "CodeBuildSdlcPost",
                        "InputArtifacts": [
                        {
                            "Name": "SourceOutput"
                        }
                        ],
                        "RunOrder": 3,
                        "RoleArn": {
                            "Fn::Sub":"arn:aws:iam::${" + env + "Account}:role/" + env_lower + "-${MasterPipeline}-scopes-${Scope}-CodeBuildRole"
                        }
                    },
                    {
                        "Ref": "AWS::NoValue"
                    }
                ]
            }
        ]
    }
    if env.lower() != 'prod':
        cicd_infra['Resources']['CodePipeline']['Properties']['Stages'].insert(-2, pipeline_sdlc_env)
    else:
        cicd_infra['Resources']['CodePipeline']['Properties']['Stages'].append(pipeline_sdlc_env)


assume_role_statement['Fn::If'][1]['Resource'] = base_statement[:]
kms_key_statement['Fn::If'][1]['Principal']['AWS'] = base_statement[:]
s3_bucket_statement['Fn::If'][1]['Principal']['AWS'] = base_statement[:]
s3_bucket_statement['Fn::If'][1]['Principal']['AWS'].append(
    {
        "Fn::Sub": "arn:aws:iam::${AWS::AccountId}:role/${Environment}-${MasterPipeline}-scopes-${Scope}-CodePipelineRole"
    }
)

# Loop through infra scopes within pipeline file
for scope, scope_value in scopes.items():
    scope_lower = scope.lower()
    # Determine AllEnvironmentsCreated value
    if scope_lower not in child_stack_parameters:
        aec = False
    if aec:
        aec = list(filter(lambda item: item['ParameterKey'] == 'AllEnvironmentsCreated', child_stack_parameters[scope_lower]))[0]['ParameterValue']
    
    # Insert Scope CICD Stack into Parent
    cicd_parent['Resources'][scope_lower] = {
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
                "AllEnvironmentsCreated": str(aec),
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
                "Fn::Sub": "https://s3.amazonaws.com/${S3BucketName}/generated-cicd-templates/" + file_cicd_child + "-" + scope_lower + ".template"
            }
        }
    }
    
    # # Add Account Parameters to the parent's stack child stack parameters
    # for env in environments:
    #     cicd_parent['Resources'][scope]['Properties']['Parameters'][env + 'Account'] = { "Ref": env + 'Account' }
    
    # Open child template to insert pipelines
    with open('scope-templates/' + file_cicd_child + '.template') as cc_file:
        cicd_child = json.load(cc_file)
        
    # Add account parameters to child stack parameters
    for env, env_value in environments.items():
        cicd_child['Parameters'][env + 'Account'] = { "Type": "Number", "Default": env_value['AccountId'] }
    
    # Add cross account policies we created above
    cicd_child['Resources']['IamPolicyBaseline']['Properties']['PolicyDocument']['Statement'].append(assume_role_statement)
    cicd_child['Resources']['KmsKey']['Properties']['KeyPolicy']['Statement'].append(kms_key_statement)
    cicd_child['Resources']['S3BucketPolicy']['Properties']['PolicyDocument']['Statement'].append(s3_bucket_statement)
    # Loop through pipelines
    if 'Pipelines' in scope_value:
        for pipeline in scope_value['Pipelines']:
            name = pipeline['Name'].lower()
            cicd_child['Resources']['Pipeline' + pipeline['Name']] = {
                "Type": "AWS::CloudFormation::Stack",
                "Condition": "NotInitialCreation",
                "DependsOn": ["RoleCodePipeline", "RoleCodeBuild"],
                "Properties": {
                    "Parameters": {
                        "MasterPipeline": {
                            "Ref": "MasterPipeline"
                        },
                        "Scope": scope_lower,
                        "SubScope": name,
                        "Environment": "cicd",
                        "S3BucketName": {
                            "Ref": "S3Bucket"
                        },
                        "KmsCmkArn": {
                            "Fn::GetAtt": [
                                "KmsKey",
                                "Arn"
                            ]
                        },
                        "IamRoleArnCodePipeline": {
                            "Fn::GetAtt": [
                                "RoleCodePipeline",
                                "Arn"
                            ]
                        },
                        "IamRoleArnCodeBuild": {
                            "Fn::GetAtt": [
                                "RoleCodeBuild",
                                "Arn"
                            ]
                        }
                    },
                    "Tags": [{
                        "Key": "Environment",
                        "Value": {
                            "Fn::Sub": "${Environment}"
                        }
                    }],
                    "TemplateURL": {
                        "Fn::Sub": "https://s3.amazonaws.com/${MasterS3BucketName}/infra-templates/CICD.template"
                    }
                }
            }
            
            # Add Account Parameters To child stack Stack parameters
            for env in environments:
                cicd_child['Resources']['Pipeline' + pipeline['Name']]['Properties']['Parameters'][env + 'Account'] = { "Ref": env + 'Account' }
            
            # Add Parameter Overrides
            if 'Parameters' in pipeline:
                for po, po_value in pipeline['Parameters'].items():
                    # Filter to parameters only applicable to CICD stack
                    if po == 'SdlcCodeBuildPre' or po == 'SdlcCodeBuildPost' or po == 'SdlcCloudFormation' or po == 'CfContainsLambda' or po == 'CicdCodeBuild' or po == 'CicdCodeBuildImage' or po == 'IncludeEnvCfTemplateConfigs':
                        cicd_child['Resources']['Pipeline' + pipeline['Name']]['Properties']['Parameters'][po] = po_value
        
    with open('generated-cicd-templates/' + file_cicd_child + '-' + scope_lower + '.template', 'w') as cc_file_output:
        json.dump(cicd_child, cc_file_output, indent=4)
        
# Save files
with open('generated-cicd-templates/' + file_cicd_parent + '.template', 'w') as cp_file_output:
    json.dump(cicd_parent, cp_file_output, indent=4)