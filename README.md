# Pipes
The purpose of this project is to easily manage AWS cross-account SDLC permissions that have traditionally been difficult to automate and maintain.
This can also manage cross-account codepipeline's as well (The original intent of this project).
One might assume that because most software companies follow the same SDLC process, that this framework should have already existed for AWS. But alas...

## Core Concepts:
   - SDLC: Software Development Life Cycle
   - Scope: A list of policies that primarily uses a specific name/tag to control access to AWS resources. Typically this value is the name of a service or microservice. Can be configured to access resources outside of the base name/tag.
   - Services should never cross environment boundaries. The environment should be the first prefix for resource names within AWS.
   - A pipeline runs within 1 scope, but a scope may have multiple pipelines.
  

## Config Files - There are 4 config files used to configure this project.
   - Environment: A list of your environments. (e.g dev, qa, prod)
   - Scopes: A list of scope definitions. (e.g. microservice1, serviceA, backupservice, orders)
   - Groups: A list of group definitions. (e.g. admins, managers, developers, team1)
   - Users: A list of user definitons. (e.g. bob, sara, testuser)

Roles for internal users are generated on a per user per environment basis. These roles should be assumed from your organizations SSO account. Users can be assigned to multiple scoped. Users can also be assigned to groups.

What this currently manages:
   - Policies
   - Scoped Roles/Policies for CodePipeline, CloudFormation, and CodeBuild.
   - Scoped User permissions via Scope assignments.

## Architecture Diagram
![Diagram](https://farrantch.github.io/pipes.png)

## Setting up the master pipeline
Within your cicd account, run the Master.template through CloudFormation.
   - Name the stack "master" or something similar (lowercase)
   - Set AllEnvironmentsCreated: False
   - Leave SourceCodeCommitRepo blank to create a repo. Fill with "codecommit:repo-name" to point to an existing repo. Fill with "github:repo-url:key" to link to a github repo.
   
Once finished, copy the KmsCmkArn and S3BucketName from the CloudFormation outputs section.
    
For every SDLC environment (aka: cicd, dev, qa, prod), run the Master-Environment.template within each environment through CloudFormation. The cicd environment is required! All others are optional.
   - Name the stack ${Environment}-{MasterStackName} ie: cicd-master (lowercase)
   - Pass in the KmsCmkArn and S3BucketName as parameters
   - Set environment (lowercase)
   - Set AccountId of cicd account
   - Pass in name of master stack (lowercase)

After SDLC stacks have been created, do the following:
   - Copy this repo into the source CodeCommit repo we configured for the master pipeline.
   - remove the ".example" from the Config-* file names.
   - Update the cfvars/Master.template file with your account ids.
   - Configure the environments file. Order matters for pipeline ordering!
   - Set AllEnvironmentsCreated = True

## Child Pipelines
Edit your Pipelines.template file as needed. Enjoy!

## To-Do
   - Option to store GitHub key elsewhere.
   - Add optional deploy to ECS step
   - Cross Region support
   - Inline policies
   - YAML support?
   - Ability to have Masters pipeline in separate account than CICD account
   - Ability for child pipelines to self update?
   - Add optional pipeline scanning step
   - Groups for users?
   - Ability to change name of CICD account.

