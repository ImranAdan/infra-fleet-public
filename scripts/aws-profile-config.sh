#!/usr/bin/env bash

# Shared validation for the fixed AWS staging strategy. This file is sourced by
# tracked Fleet scripts; configuration cannot select another implementation.

aws_profile_fail() {
  echo "$*" >&2
  return 1
}

aws_profile_load_config() {
  local repository_root=$1
  local config_file="${CONFIG_FILE:-$repository_root/config.env}"
  local name

  if [ ! -f "$config_file" ]; then
    aws_profile_fail "Missing $config_file. Copy config.example.env to config.env first."
    return 1
  fi

  # config.env is an operator-owned shell environment file. Credentials stay
  # in the caller's session or are entered interactively during apply.
  set -a
  # shellcheck disable=SC1090
  source "$config_file"
  set +a

  for name in \
    GITHUB_REPOSITORY \
    GITHUB_DEPLOYMENT_BRANCH \
    GITHUB_DEPLOYMENT_ENVIRONMENT \
    TF_CLOUD_ORGANIZATION \
    TF_WORKSPACE_PERMANENT \
    TF_WORKSPACE_STAGING; do
    if [ -z "${!name:-}" ] || [[ "${!name}" == *CHANGE_ME* ]]; then
      aws_profile_fail "$name is unset or still contains CHANGE_ME in $config_file."
      return 1
    fi
  done

  if [[ ! "$GITHUB_REPOSITORY" =~ ^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$ ]]; then
    aws_profile_fail 'GITHUB_REPOSITORY must use OWNER/REPOSITORY form.'
    return 1
  fi
  if [ "$GITHUB_DEPLOYMENT_BRANCH" != main ]; then
    aws_profile_fail 'The supplied workflows currently support GITHUB_DEPLOYMENT_BRANCH=main only.'
    return 1
  fi
  if [ "$GITHUB_DEPLOYMENT_ENVIRONMENT" != staging ]; then
    aws_profile_fail 'The AWS profile requires GITHUB_DEPLOYMENT_ENVIRONMENT=staging.'
    return 1
  fi
  if [[ ! "$TF_CLOUD_ORGANIZATION" =~ ^[A-Za-z0-9_-]+$ ]]; then
    aws_profile_fail 'TF_CLOUD_ORGANIZATION contains unsupported characters.'
    return 1
  fi
  for name in TF_WORKSPACE_PERMANENT TF_WORKSPACE_STAGING; do
    if [[ ! "${!name}" =~ ^[A-Za-z0-9_-]+$ ]]; then
      aws_profile_fail "$name contains unsupported characters."
      return 1
    fi
  done
  # Terraform reads this as set(string); accept only a JSON array of IAM ARN
  # strings so a malformed value fails here rather than mid-deployment.
  local arn='"arn:aws[a-z-]*:iam::[0-9]{12}:[^"[:space:]]+"'
  local arns="^\\[[[:space:]]*($arn([[:space:]]*,[[:space:]]*$arn)*)?[[:space:]]*\\]$"
  # AWS tag values allow letters, digits, spaces and _.:/=+-@ only.
  local tag_value='^[A-Za-z0-9_.:/=+@ -]+$' owner=${COST_OWNER:-infra-fleet}
  if [[ ! "$owner" =~ $tag_value ]] || [ "${#owner}" -gt 256 ]; then
    aws_profile_fail 'COST_OWNER must be a valid AWS tag value.'
    return 1
  fi
  if [[ ! "${EKS_ADMIN_PRINCIPAL_ARNS_JSON:-[]}" =~ $arns ]]; then
    aws_profile_fail 'EKS_ADMIN_PRINCIPAL_ARNS_JSON must be a JSON array of IAM ARN strings.'
    return 1
  fi

  AWS_PROFILE_CONFIG_FILE=$config_file
  export AWS_PROFILE_CONFIG_FILE
}
