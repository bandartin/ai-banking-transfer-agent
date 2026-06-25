# AWX Quick Start

## Overview
This quick start shows the shortest path to create and deploy an AWX flow artifact.

## Step 1
Prepare the current `flow/` workspace with `awx init --source blank` or `awx clone --source builtin --name mcp-agent-sdk-auto`.

## Step 2
Run the current flow with `awx run` and verify that `flow/run-application.sh` starts successfully.

## Step 3
Before `awx package`, confirm Portal settings are ready and that offline environments only use internal Portal or mirror resources.

## Step 4
Run `awx package --message "deploy test"` to create the artifact and request deployment.

## Expected result
You should see an artifact identifier and deployment result from the AWX packaging flow.

## What's next
If you need a local checkpoint before overwrite, use `awx stash --message "<text>"`. Advanced tutorials stay outside this quick start.
