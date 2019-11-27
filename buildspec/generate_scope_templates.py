import boto3
import sys
import time
import os
import json
import urllib.parse
import generate_user_templates
from argparse import ArgumentParser
from utils import *
from botocore.config import Config

# Max retry config
config = Config(
    retries = dict(
        max_attempts = 10
    )
)

def get_cicd_stack_outputs():
    cf_client = boto3.client('cloudformation', config=config)
    # Get main infra stack resources
    resource_summaries = cf_client.list_stack_resources(
        StackName=MAIN_PIPELINE_STACK
    )['StackResourceSummaries']

    # Get cicd child stack outputs
    child_stack_outputs = {}
    # Loop through main infra stack resources
    for rs in resource_summaries:
        # Only look for CloudFormation Stacks
        if rs['ResourceType'] == 'AWS::CloudFormation::Stack':
            # Get Stack outputs
            child_stack_outputs[rs['LogicalResourceId']] = cf_client.describe_stacks(
                StackName = rs['PhysicalResourceId']
            )['Stacks'][0]['Outputs']
    return child_stack_outputs

def generate_scope_templates(environment_type, child_stack_outputs):
    # Open Files
    scopes = read_file(FILE_CONFIG_SCOPES)
    scope_parent = read_file('templates/' + FILE_TEMPLATE_SCOPES_PARENT)

    # Loop through infra scopes within pipeline file
    for key, value in scopes.items():
        scope = key
        
        # Determine stack output values
        s3_bucket_name = list(filter(lambda item: item['OutputKey'] == 'S3BucketName', child_stack_outputs[scope]))[0]['OutputValue']
        kms_key_arn = list(filter(lambda item: item['OutputKey'] == 'KmsKeyArn', child_stack_outputs[scope]))[0]['OutputValue']
        
        scope_parent['Resources'][scope] = {
            "Type" : "AWS::CloudFormation::Stack",
            "Properties": {
                "Parameters": {
                    "S3BucketName": s3_bucket_name,
                    "CicdAccount": {
                        "Ref": "CicdAccount"
                    },
                    "KmsKeyArn": kms_key_arn,
                    "MainPipeline": {
                        "Ref": "MainPipeline"
                    },
                    "Environment": {
                        "Ref": "Environment"
                    },
                    "Scope": scope,
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
                    "Fn::Sub": "https://s3.amazonaws.com/${S3BucketName}/generated-scope-templates-" + environment_type.lower() + "/Scopes-Child-" + scope + ".template"
                }
            }
        }
        
        # Open child template to insert CodeBuildProjects
        scope_child = read_file('templates/' + FILE_TEMPLATE_SCOPES_CHILD)
            
        scope_child = add_policy_statements(scope_child, scope, value, environment_type)

        # Consolidate Policies
        scope_child['Resources']['IamPolicyService']['Properties']['PolicyDocument']['Statement'] = consolidate_statements(
            scope_child['Resources']['IamPolicyService']['Properties']['PolicyDocument']['Statement']
        )

        scope_child['Resources']['IamPolicyDeploy']['Properties']['PolicyDocument']['Statement'] = consolidate_statements(
            scope_child['Resources']['IamPolicyDeploy']['Properties']['PolicyDocument']['Statement']
        )

        scope_child['Resources']['IamPolicyPipeline']['Properties']['PolicyDocument']['Statement'] = consolidate_statements(
            scope_child['Resources']['IamPolicyPipeline']['Properties']['PolicyDocument']['Statement']
        )

        # Save child file
        write_file('generated-scope-templates-' + environment_type.lower() + '/' + FILE_TEMPLATE_SCOPES_CHILD + '-' + scope, scope_child)

    # Save parent file
    write_file('generated-scope-templates-' + environment_type.lower() + '/' + FILE_TEMPLATE_SCOPES_PARENT, scope_parent)

def main():
    # Parse arguments
    parser = ArgumentParser()
    parser.add_argument("-et", "--environment_type", help="Choose environment type. Ex - 'Sdlc' or 'Cicd'")
    args = parser.parse_args()

    # Get outputs from cicd child stacks
    child_stack_outputs = get_cicd_stack_outputs()

    # Generate scope templates with CICD child stack outputs
    generate_scope_templates(args.environment_type, child_stack_outputs)

if __name__ == "__main__":
    main()