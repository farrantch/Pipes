import boto3
import sys
import time
import os

client = boto3.client('cloudformation')

MASTERINFRASTACK = os.environ['MasterInfraStack']
ENVIRONMENT = os.environ['Environment']

# List master infra stack resources
resource_summaries = client.list_stack_resources(
    StackName=MASTERINFRASTACK
)['StackResourceSummaries']

# Update Stacks
change_sets = []
for rs in resource_summaries:
    if rs['ResourceType'] == 'AWS::CloudFormation::Stack':
        stack_parameters = client.describe_stacks(
            StackName = rs['PhysicalResourceId']
        )['Stacks'][0]['Parameters']
        stack_parameters[:] = [d for d in stack_parameters if d.get('ParameterKey') != 'AllEnvironmentsCreated']
        stack_parameters.append(
                {
                    'ParameterKey': 'AllEnvironmentsCreated',
                    'ParameterValue': 'True',
                    'UsePreviousValue': False
                }
            )
        # Create Change Set
        change_set_id = client.create_change_set(
            StackName = rs['PhysicalResourceId'],
            UsePreviousTemplate=True,
            Capabilities=[
                'CAPABILITY_IAM',
                'CAPABILITY_NAMED_IAM',
                'CAPABILITY_AUTO_EXPAND',
            ],
            Parameters=stack_parameters,
            ChangeSetName=ENVIRONMENT + '-' + rs['LogicalResourceId'],
            ChangeSetType='UPDATE'
        )['Id']
        change_set_description = {}
        # Wait for change set to finish creating
        while change_set_description == {} or change_set_description['Status'] == 'CREATE_PENDING' or change_set_description['Status'] == 'CREATE_IN_PROGRESS':
            change_set_description = client.describe_change_set(
                ChangeSetName=ENVIRONMENT + '-' + rs['LogicalResourceId'],
                StackName=rs['PhysicalResourceId']
            )
        # If created, execute change set
        if change_set_description['Status'] != 'FAILED':
            change_set_status = client.execute_change_set(
                ChangeSetName=ENVIRONMENT + '-' + rs['LogicalResourceId'],
                StackName=rs['PhysicalResourceId']
            )
            # Add to wait to finish list
            change_sets.append(
                {
                    'ChangeSetId': change_set_id,
                    'ChangeSetName': ENVIRONMENT + '-' + rs['LogicalResourceId'],
                    'StackName': rs['PhysicalResourceId']
                }
            )

# Wait for change sets to finish executing
for cs in change_sets:
    execution_status = ''
    while execution_status == '' or execution_status == 'UNAVAILABLE' or execution_status == 'AVAILABLE' or execution_status == 'EXECUTE_IN_PROGRESS':
        execution_status = client.describe_change_set(
            ChangeSetName = cs['ChangeSetId']
        )['ExecutionStatus']
        time.sleep(1)