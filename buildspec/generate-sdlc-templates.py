import boto3
import sys
import time
import os
import json
import urllib.parse
import generate_users_template
from utils import add_policy_statements, get_policy_statements, consolidate_statements

# Filenames
file_scopes = 'Config-Scopes'
file_sdlc_parent = 'Scope-SDLC-Parent'
file_sdlc_child = 'Scope-SDLC-Child'

# Open Files
# Input Files
with open(file_scopes + '.template') as s_file:
    scopes = json.load(s_file)
with open('templates/' + file_sdlc_parent + '.template') as sp_file:
    sdlc_parent = json.load(sp_file)
    
cf_client = boto3.client('cloudformation')

#MASTERSCOPESTACK = os.environ['MASTERSCOPESTACK']
#ENVIRONMENT = os.environ['Environment']

MASTERSCOPESTACK = 'cicd-master-scopes'
# ENVIRONMENT = 'cicd'

# Get master infra stack resources
resource_summaries = cf_client.list_stack_resources(
    StackName=MASTERSCOPESTACK
)['StackResourceSummaries']

# Get cicd child stack outputs
child_stack_outputs = {}
# Loop through master infra stack resources
for rs in resource_summaries:
    # Only look for CloudFormation Stacks
    if rs['ResourceType'] == 'AWS::CloudFormation::Stack':
        # Get Stack outputs
        child_stack_outputs[rs['LogicalResourceId']] = cf_client.describe_stacks(
            StackName = rs['PhysicalResourceId']
        )['Stacks'][0]['Outputs']

# Loop through infra scopes within pipeline file
for key, value in scopes.items():
    scope = key.lower()
    create_kms_key_scope = value.get('CreateKmsKeyScope', "False")
    
    # Determine stack output values
    s3_bucket_name = list(filter(lambda item: item['OutputKey'] == 'S3BucketName', child_stack_outputs[scope]))[0]['OutputValue']
    kms_cmk_arn = list(filter(lambda item: item['OutputKey'] == 'KmsCmkArn', child_stack_outputs[scope]))[0]['OutputValue']
    
    sdlc_parent['Resources'][scope] = {
          "Type" : "AWS::CloudFormation::Stack",
          "Properties": {
            "Parameters": {
                "S3BucketName": s3_bucket_name,
                "CicdAccount": {
                    "Ref": "CicdAccount"
                },
                "KmsCmkArn": kms_cmk_arn,
                "MasterPipeline": {
                    "Ref": "MasterPipeline"
                },
                "Environment": {
                    "Ref": "Environment"
                },
                "Scope": scope,
                "MasterS3BucketName": {
                    "Fn::Sub": "${S3BucketName}"
                },
                "CreateKmsKeyScope": create_kms_key_scope
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
                "Fn::Sub": "https://s3.amazonaws.com/${S3BucketName}/generated-sdlc-templates/Scope-SDLC-Child-" + scope + ".template"
            }
        }
    }
    
    # Open child template to insert CodeBuildProjects
    with open('templates/' + file_sdlc_child + '.template') as sc_file:
        sdlc_child = json.load(sc_file)
        
    sdlc_child = add_policy_statements(sdlc_child, scope, value, 'Sdlc')

    # Add KmsKeyService policy if specified
    create_kms_key_scope = value.get('CreateKmsKeyScope', 'False')
    if create_kms_key_scope == 'True':
        sdlc_child['Resources']['IamPolicyService']['Properties']['PolicyDocument']['Statement'].append(
            {
                "Sid": "KmsKeyScope",
                "Effect": "Allow",
                "Action": [
                    "kms:Get*",
                    "kms:List*",
                    "kms:Describe*",
                    "kms:GenerateDataKey",
                    "kms:PutKeyPolicy",
                    "kms:ReEncrypt*",
                    "kms:Encrypt",
                    "kms:DescribeKey",
                    "kms:Decrypt"
                ],
                "Resource": [
                    {
                        "Fn::GetAtt": [
                            "KmsKeyScope",
                            "Arn"
                        ]
                    }
                ]
            }
        )
    
    # Consolidate Policies
    sdlc_child['Resources']['IamPolicyService']['Properties']['PolicyDocument']['Statement'] = consolidate_statements(
        sdlc_child['Resources']['IamPolicyService']['Properties']['PolicyDocument']['Statement']
    )

    sdlc_child['Resources']['IamPolicyDeploy']['Properties']['PolicyDocument']['Statement'] = consolidate_statements(
        sdlc_child['Resources']['IamPolicyDeploy']['Properties']['PolicyDocument']['Statement']
    )

    sdlc_child['Resources']['IamPolicyPipeline']['Properties']['PolicyDocument']['Statement'] = consolidate_statements(
        sdlc_child['Resources']['IamPolicyPipeline']['Properties']['PolicyDocument']['Statement']
    )
    
    with open('generated-sdlc-templates/' + file_sdlc_child + '-' + scope + '.template', 'w') as sc_file_output:
        json.dump(sdlc_child, sc_file_output, indent=4)
    
# Save files
with open('generated-sdlc-templates/' + file_sdlc_parent + '.template', 'w') as sp_file_output:
    json.dump(sdlc_parent, sp_file_output, indent=4)

generate_users_template.generate_users_template('generated-sdlc-templates/', "Sdlc")