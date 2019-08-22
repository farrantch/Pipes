# Pipes
The purpose of this project is to easily manage AWS cross-account permissions that have traditionally been difficult to automate and maintain.
One might assume that because most software companies follow the same SDLC process, that this framework should have already existed for AWS. But alas...

## Core Concepts:
   - SDLC: Software Development Life Cycle
   - Environment: Self explanatory. The most important permissions boundary of all! Never cross environment boundaries. Always the first prefix for named resources.
   - Scope: A logical permissions boundary used within an environment to segregate services. Often used for a microservice's permission boundary.
   -
What this currently manages:
   - Scoped CodePipelines
   - Roles/Policies for CodePipeline, CloudFormation, and CodeBuild.
   - User permissions via scope assignments.

## Architecture Diagram
![Diagram](https://farrantch.github.io/pipes.png)

## Set up the master pipeline
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

