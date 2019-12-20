import json
import boto3
import os
import string

iam_client = boto3.client('iam')

# Variables
FILE_CONFIG_SCOPES = 'Config-Scopes'
FILE_CONFIG_ENVIRONMENTS = 'Config-Environments'
FILE_CONFIG_USERS = 'Config-Users'
FILE_CONFIG_KEYS = 'Config-Keys'
FILE_CONFIG_GROUPS = 'Config-Groups'
FILE_TEMPLATE_MAIN = 'Main'
FILE_TEMPLATE_USERS_CHILD = 'Users-Child'
FILE_TEMPLATE_USERS_PARENT = 'Users-Parent'
FILE_TEMPLATE_SCOPES_PARENT = 'Scopes-Parent'
FILE_TEMPLATE_SCOPES_CHILD = 'Scopes-Child'
FILE_TEMPLATE_PIPELINES_PARENT = 'Pipelines-Parent'
FILE_TEMPLATE_PIPELINES_CHILD = 'Pipelines-Child'
FILE_TEMPLATE_KEYS_PARENT = 'Keys-Parent'
FILE_TEMPLATE_KEYS_CHILD = 'Keys-Child'
MAINSCOPESTACK = 'cicd-main-scopes'
MAIN_PIPELINE_STACK = 'cicd-main-pipelines'
OUTPUT_FOLDER = 'output'
BUILD_NUM = os.environ['buildnum']
ENVIRONMENT = os.environ['Environment']
#BUILD_NUM = '1'
#ENVIRONMENT = 'cicd'

# Get IAM AWS Managed policy statements
def get_policy_statements(policy_arn):
    policy_version = iam_client.get_policy(
        PolicyArn=policy_arn
    )['Policy']['DefaultVersionId']
    policy_statement = iam_client.get_policy_version(
        PolicyArn=policy_arn,
        VersionId=policy_version
    )['PolicyVersion']['Document']['Statement']
    for statement in policy_statement:
        if type(statement['Resource']) is not list:
            statement['Resource'] = [statement['Resource']]
        if type(statement['Action']) is not list:
            statement['Action'] = [statement['Action']]
        if 'Condition' in statement:
            for condition, condition_content in statement['Condition'].items():
                for condition_key, condition_value in condition_content.items():
                    if type(condition_value) is str:
                        statement['Condition'][condition][condition_key] = [ condition_value ]
    return policy_statement

# Open file
def read_file(location):
    with open(location + '.template') as f:
        contents = json.load(f)
    f.close()
    return contents

# Save file
def write_file(location, contents):
    # Create directory if doesn't exist
    os.makedirs(os.path.dirname(location + '.template'), exist_ok=True)
    # Save Pipeline Template file
    with open(location + '.template', 'w') as f:
        json.dump(contents, f, indent=4)
    f.close()

# Calculate number of characters in an object
def num_characters(o):
    string_o = json.dumps(o)
    string_o = string_o.translate({ord(c): None for c in string.whitespace})
    return len(string_o)

# Add policy statements from config files
def add_policy_statements(template, scope, scope_value, environment):
    # Only add policies if exists
    if 'Policies' in scope_value:
        # If environment doesn't exist, set to default
        if environment not in scope_value['Policies']:
            environment = 'Default'
        if environment in scope_value['Policies']:
            # Add scoped/* if exists
            if 'scoped/*' in scope_value['Policies'][environment]:
                for filename in os.listdir('policies/scoped'):
                    with open('policies/scoped/' + filename) as f:
                        d = json.load(f)
                    if 'PipelineStatements' in d:
                        for s in d['PipelineStatements']:
                            template['Resources']['IamPolicyPipeline']['Properties']['PolicyDocument']['Statement'].append(s)
                    if 'ServiceStatements' in d:
                        for s in d['ServiceStatements']:
                            template['Resources']['IamPolicyService']['Properties']['PolicyDocument']['Statement'].append(s)
                    if 'DeployStatements' in d:
                        for s in d['DeployStatements']:
                            template['Resources']['IamPolicyDeploy']['Properties']['PolicyDocument']['Statement'].append(s)
            # Add rest of policies
            for ps in scope_value['Policies'][environment]:
                # Add scoped policy if isn't scoped/*
                if ps != 'scoped/*':
                    # Don't re-add resource-scope policies if already added via wildcard
                    if not ps.startswith('scoped/') or 'scoped/*' not in scope_value['Policies'][environment]:
                        # Parse everything before ':' to get file name
                        policyname_split = ps.split(':')
                        with open('policies/' + str(policyname_split[0]) + '.template') as json_file:
                            data = json.load(json_file)
                        # If contains alternative scope name, replace scope within file
                        if len(policyname_split) > 1:
                            data = json.loads(json.dumps(data).replace('${Scope}', policyname_split[1]))
                        if 'PipelineStatements' in data:
                            for statement in data['PipelineStatements']:
                                # AWS Policies
                                if 'PolicyArn' in statement:
                                    template['Resources']['IamPolicyPipeline']['Properties']['PolicyDocument']['Statement'].extend(get_policy_statements(statement['PolicyArn']))
                                # Inline Policies
                                else:
                                    template['Resources']['IamPolicyPipeline']['Properties']['PolicyDocument']['Statement'].append(statement)
                        if 'ServiceStatements' in data:
                            for statement in data['ServiceStatements']:
                                # AWS Policies
                                if 'PolicyArn' in statement:
                                    template['Resources']['IamPolicyService']['Properties']['PolicyDocument']['Statement'].extend(get_policy_statements(statement['PolicyArn']))
                                # Inline Policies
                                else:
                                    template['Resources']['IamPolicyService']['Properties']['PolicyDocument']['Statement'].append(statement)
                        if 'DeployStatements' in data:
                            for statement in data['DeployStatements']:
                                if 'PolicyArn' in statement:
                                    template['Resources']['IamPolicyDeploy']['Properties']['PolicyDocument']['Statement'].extend(get_policy_statements(statement['PolicyArn']))
                                else:
                                    template['Resources']['IamPolicyDeploy']['Properties']['PolicyDocument']['Statement'].append(statement)
    return template

# Check if a policy's actions contains a specific service
def action_contains_service(service, action):
    if len(action) > 0:
        # List of String
        if type(action) is list:
            for item in action:
                if item.split(':')[0] == service:
                    return True
        # String
        else:
            if action.split(':')[0] == service:
                return True
        # Tests passed.
    return False

# Check if a policy's resources contains a specific service
def resource_contains_service(service, resource):
    if len(resource) > 0:
        # List
        if type(resource) is list:
            for item in resource:
                # List of Dict
                if type(item) is dict:
                    for key, value in item.items():
                        if key != "Fn::Sub":
                            return False
                        if value.split(':')[2] == service:
                            return True
                # List of String
                else:
                    if item.split(':')[2] == service:
                        return True
        # Dict
        elif type(resource) is dict:
            for key, value in resource.items():
                if value.split(':')[2] == service:
                    return True
        # String
        else:
            if resource.split(':')[2] == service:
                return True
    # Tests passed.
    return False

# Checks to see if 2 given statements are mergable
def is_statements_mergable(statement1, statement2):
    # Effect
    if statement1['Effect'] != statement2['Effect']:
        return False
    # Action
    # Make sure both are either wildcard or non wildcard
    if (statement1['Action'] == "*" or statement1['Action'] == ["*"]) != (statement2['Action'] == "*" or statement2['Action'] == ["*"]):
        return False
    # Can merge actions if wildcard
    if statement1['Action'] != '*' and statement1['Action'] != ['*']:
        for action in statement1['Action']:
            service = action.split(':')[0]
            # If resources are wildcard, we don't need to check if action contains service
            if (statement1['Resource'] != "*" and statement1['Resource'] != ["*"]) or (statement2['Resource'] != "*" and statement2['Resource'] != ["*"]):
                if action_contains_service(service, statement2['Action']):
                    return False
            # # Not really necessary, but just in case
            # elif resource_contains_service(service, statement2['Resource']):
            #     return False
    # Resource -- Kinda taken care of above. But need to implement in the future just in case
    # Make sure both are either wildcard or non wildcard
    if (statement1['Resource'] == "*" or statement1['Resource'] == ["*"]) != (statement2['Resource'] == "*" or statement2['Resource'] == ["*"]):
        return False
    if statement1['Resource'] != '*' and statement1['Resource'] != ['*']:
        #print(statement1)
        for resource in statement1['Resource']:
            # Get AWS Service
            service = ""
            # String
            if type(resource) is str:
                service = resource.split(':')[2]
            # Dict
            else:
                for key, value in resource.items():
                    if key != "Fn::Sub":
                        return False
                    if type(value) is list:
                        return False
                    service = value.split(':')[2]
            if resource_contains_service(service, statement2['Resource']):
                return False

    # Condition
    # Make sure conditions either both exist or both don't
    if ('Condition' in statement1) != ('Condition' in statement2):
        return False
    if 'Condition' in statement1:
        if statement1['Condition'] != statement2['Condition']:
            return False
    # Passed
    return True

# Consolidates a list of statements
def consolidate_statements(statements):
    # Create arrays for each iteration of consolidating
    statements_merged_sids = []
    statements_merged_intelligent = []
    statements_split_size = []

    # Group Similar SID's
    statement_map = {}
    for s in statements:
        # Skip all merging if NotAction or NotResource
        if 'NotAction' in s or 'NotResource' in s:
            statements_split_size.append(s)
        # Skip merging by sids if doesn't exist and add directly to statements_merged_sids list
        elif 'Sid' not in s:
            statements_merged_sids.append(s)
        # Sid exists, add to statement map if doesn't exist
        else:
            if s["Sid"] not in statement_map:
                statement_map[s["Sid"]] = []
            statement_map[s["Sid"]].append(s)
    # Loop through SID statements and combine resources
    for sid, statement_list in statement_map.items():
        # Loop through the rest of the statements
        base_sid_statement = {}
        for statement in statement_list:
            # If base_sid_statement not set yet, use statement for base_sid_statement
            if not base_sid_statement:
                base_sid_statement = statement
                # Make Resource a list if isn't already
                if type(base_sid_statement['Resource']) is dict:
                    base_sid_statement['Resource'] = [
                        base_sid_statement['Resource']
                    ]
            # If does exist, merge statement into base_sid_statement
            else:
                # Add resources to base_sid_statement
                # If resource wildcard, don't merge resources
                if statement['Resource'] != "*" and statement['Resource'] != ["*"]:
                    # Multiple Resources
                    if type(statement['Resource']) is list:
                        for resource in statement['Resource']:
                            # Check if key value pair exist in resources
                            for key, value in resource.items():
                                if not any(d.get(key, None) == value for d in base_sid_statement['Resource']):
                                    base_sid_statement['Resource'].append(resource)
                    # Single resource
                    elif type(statement['Resource']) is dict:
                        for key, value in statement['Resource'].items():
                            if not any(d.get(key, None) == value for d in base_sid_statement['Resource']):
                                base_sid_statement['Resource'].append(statement['Resource'])

                # Add Conditions to base_sid_statement
                if 'Condition' in statement:
                    for condition, condition_value in statement['Condition'].items():
                        for statement_name, statement_value in condition_value.items():
                            for item in statement_value:
                                if type(item) is str:
                                    if item not in base_sid_statement['Condition'][condition][statement_name]:
                                        base_sid_statement['Condition'][condition][statement_name].append(item)
                                else:
                                    for key, value in item.items():
                                        # Check if key value pair exists in condition_value
                                        if not any(d.get(key, None) == value for d in base_sid_statement['Condition'][condition][statement_name]):
                                            # If not, insert it
                                            base_sid_statement['Condition'][condition][statement_name].append({key: value})
        if base_sid_statement:
            statements_merged_sids.append(base_sid_statement)
    #return statements_merged_sids

    # Perform final merge of SIDs
    for statement in statements_merged_sids:
        # Create Sid prefix string used for statement
        sid_effect = statement['Effect']
        sid_action = "ActWild" if statement['Action'] == "*" or statement['Action'] == ["*"] else "ActScope"
        sid_resource = "ResWild" if statement['Resource'] == "*" or statement['Resource'] == ["*"] else "ResScope"
        sid_condition = "Cond" if 'Condition' in statement else "NoCond"
        sid = sid_effect + sid_action + sid_resource + sid_condition
        # Search for existing sids with matching pattern
        results = list(filter(lambda statement: statement['Sid'].startswith(sid), statements_merged_intelligent))
        merged = False
        num_results = len(results)
        for result in results:
            if is_statements_mergable(result, statement):
                # Add Resources
                if sid_resource != "ResWild":
                    for resource in statement['Resource']:
                        result['Resource'].append(resource)
                # Add Actions
                if sid_action != "ActWild":
                    for action in statement['Action']:
                        if action not in result['Action']:
                            result['Action'].append(action)
                # Add Conditions
                if 'Condition' in statement:
                    for condition, condition_content in statement['Condition'].items():
                        for condition_key, condition_value in condition_content.items():
                            for item in condition_value:
                                if type(item) is dict:
                                    for key, value in item.items():
                                        if not any(d.get(key, None) == value for d in result['Condition'][condition][condition_key]):
                                            result['Condition'][condition][condition_key].append({key: value})
                                # String
                                else:
                                    if item not in result['Condition'][condition][condition_key]:
                                        result['Condition'][condition][condition_key].append(item)
                merged = True
                break
        if not merged:
            if type(statement['Action']) is not list:
                statement['Action'] = [statement['Action']]
            if type(statement['Resource']) is not list:
                statement['Resource'] = [statement['Resource']]
            item = {
                "Sid": sid + str(num_results),
                "Effect": statement['Effect'],
                "Action": statement['Action'],
                "Resource": statement['Resource']
            }
            if 'Condition' in statement:
                item['Condition'] = statement['Condition']
            # Add new statement to final list
            statements_merged_intelligent.append(item)

    # Split statement actions if too big
    # Can easily happen on resource wildcards (ex: readonly policies)
    for rs in statements_merged_intelligent:
        # Get size of statement action
        rs_size = num_characters(rs['Action'])
        # Calculate num of splits
        num_of_split_statements = (rs_size // 5900) + 1
        # No split needed
        if num_of_split_statements == 1:
            statements_split_size.append(rs)
        # Split needed
        else:
            # Calculate desired length of action post split
            statement_size = (len(rs['Action']) // num_of_split_statements) + 1
            # Peform split
            for i in range(0, len(rs['Action']), statement_size):
                item = {
                    "Effect": rs['Effect'],
                    "Resource": rs['Resource'],
                    "Sid": rs['Sid'] + 'Split' + str(i),
                    "Action": rs['Action'][i:i + statement_size]
                }
                if 'Condition' in rs:
                    item['Condition'] = rs['Condition']
                statements_split_size.append(item)

    return statements_split_size