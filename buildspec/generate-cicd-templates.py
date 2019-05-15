import boto3
import sys
import time
import os
import json
from collections import OrderedDict
from botocore.exceptions import ClientError

# Filenames
file_scopes = 'Config-Scopes'
file_environments = 'Config-Environments'
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
    
client = boto3.client('cloudformation')

#MASTERINFRASTACK = os.environ['MasterInfraStack']
#ENVIRONMENT = os.environ['Environment']

MASTERINFRASTACK = 'cicd-master-infra'
ENVIRONMENT = 'cicd'

# Get master infra stack resources
aec = True
try:
    master_stack = client.describe_stacks(
        StackName=MASTERINFRASTACK
    )
except ClientError:
    aec = False
    
if aec:
    resource_summaries = client.list_stack_resources(
        StackName=MASTERINFRASTACK
    )['StackResourceSummaries']
    # Get existing child stack parameters
    child_stack_parameters = {}
    # Loop through master infra stack resources
    for rs in resource_summaries:
        # Only look for CloudFormation Stacks
        if rs['ResourceType'] == 'AWS::CloudFormation::Stack':
            # Get Stack parameters
            child_stack_parameters[rs['LogicalResourceId']] = client.describe_stacks(
                StackName = rs['PhysicalResourceId']
            )['Stacks'][0]['Parameters']

# Loop through infra scopes within pipeline file
for key, value in scopes.items():
    scope = key.lower()
    # Determine AllEnvironmentsCreated value
    if scope not in child_stack_parameters:
        aec = False
    if aec:
        aec = list(filter(lambda item: item['ParameterKey'] == 'AllEnvironmentsCreated', child_stack_parameters[scope]))[0]['ParameterValue']
    
    # Insert Scope CICD Stack into Parent
    cicd_parent['Resources'][scope] = {
        "Type" : "AWS::CloudFormation::Stack",
        "Properties": {
            "Parameters": {
                "MasterPipeline": {
                    "Ref": "MasterPipeline"
                },
                "Environment": {
                    "Ref": "Environment"
                },
                "Scope": scope,
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
                "Fn::Sub": "https://s3.amazonaws.com/${S3BucketName}/generated-cicd-templates/Scope-CICD-Child-" + scope + ".template"
            }
        }
    }
    
    # Add Account Parameters
    for env in environments:
        cicd_parent['Resources'][scope]['Properties']['Parameters'][env + 'Account'] = { "Ref": env + 'Account' }
    
    # Open child template to insert pipelines
    with open('scope-templates/' + file_cicd_child + '.template') as cc_file:
        cicd_child = json.load(cc_file)
    
    # Loop through pipelines
    if 'Pipelines' in value:
        for pipeline in value['Pipelines']:
            name = pipeline['Name'].lower()
            cicd_child['Resources'][pipeline['Name']] = {
                "Type": "AWS::CloudFormation::Stack",
                "Condition": "NotInitialCreation",
                "DependsOn": ["RoleCodePipeline", "RoleCodeBuild"],
                "Properties": {
                    "Parameters": {
                        "MasterPipeline": {
                            "Ref": "MasterPipeline"
                        },
                        "Scope": scope,
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
            
            # Add Account Parameters
            for env in environments:
                cicd_child['Resources'][pipeline['Name']]['Properties']['Parameters'][env + 'Account'] = { "Ref": env + 'Account' }
            
            # Add Parameter Overrides
            if 'Parameters' in pipeline:
                for po, po_value in pipeline['Parameters'].items():
                    # Filter to parameters only applicable to CICD stack
                    if po == 'SdlcCodeBuildPre' or po == 'SdlcCodeBuildPost' or po == 'SdlcCloudFormation' or po == 'CfContainsLambda' or po == 'CicdCodeBuild' or po == 'CicdCodeBuildImage' or po == 'IncludeEnvCfTemplateConfigs':
                        cicd_child['Resources'][pipeline['Name']]['Properties']['Parameters'][po] = po_value
        
    with open('generated-cicd-templates/' + file_cicd_child + '-' + scope + '.template', 'w') as cc_file_output:
        json.dump(cicd_child, cc_file_output, indent=4)
        
# Save files
with open('generated-cicd-templates/' + file_cicd_parent + '.template', 'w') as cp_file_output:
    json.dump(cicd_parent, cp_file_output, indent=4)