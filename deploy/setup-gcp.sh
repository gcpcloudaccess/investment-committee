#!/usr/bin/env bash
# One-time GCP setup for GitHub Actions -> Cloud Run deployment.
#
# Run this yourself (not via Claude) - it creates IAM service accounts, a
# Workload Identity Federation pool, and Secret Manager secrets, i.e. it
# changes who/what can act on your GCP project. Review each command before
# running. Requires: gcloud CLI, authenticated as an Owner/Editor on the
# target project.
#
# Usage: bash deploy/setup-gcp.sh
set -euo pipefail

PROJECT_ID="money-minting-machine"
REGION="asia-south1"
AR_REPO="money-minting-machine"
# <org-or-user>/<repo> exactly as it appears in your GitHub remote right now.
# If you rename the GitHub repo itself, update this to match BEFORE running
# this script (the OIDC token's "repository" claim has to match exactly, or
# workload identity federation will reject the login).
GITHUB_REPO="gcpcloudaccess/investment-committee"
DEPLOYER_SA="github-deployer"
WIF_POOL="github-pool"
WIF_PROVIDER="github-provider"

echo "==> Setting active project to ${PROJECT_ID}"
gcloud config set project "${PROJECT_ID}"

echo "==> Enabling required APIs (takes a minute or two the first time)"
gcloud services enable \
  run.googleapis.com \
  artifactregistry.googleapis.com \
  iam.googleapis.com \
  iamcredentials.googleapis.com \
  secretmanager.googleapis.com \
  sts.googleapis.com

echo "==> Creating Artifact Registry Docker repo (skips if it already exists)"
gcloud artifacts repositories create "${AR_REPO}" \
  --repository-format=docker \
  --location="${REGION}" \
  --description="Investment Committee backend/frontend images" \
  || echo "   (repo already exists, continuing)"

echo "==> Creating Secret Manager secrets"
echo "    You'll be prompted for each key - input is hidden, nothing is echoed or logged."
echo "    Leave OPENAI_API_KEY / NEWSAPI_KEY blank+Enter if you don't use them (app has graceful fallbacks)."

create_secret () {
  local name="$1" prompt="$2"
  if gcloud secrets describe "${name}" >/dev/null 2>&1; then
    echo "   Secret '${name}' already exists - adding a new version instead."
    read -rsp "${prompt}: " value; echo
    printf '%s' "${value}" | gcloud secrets versions add "${name}" --data-file=-
  else
    read -rsp "${prompt}: " value; echo
    printf '%s' "${value}" | gcloud secrets create "${name}" --data-file=- --replication-policy=automatic
  fi
}

create_secret "anthropic-api-key" "ANTHROPIC_API_KEY"
create_secret "openai-api-key"    "OPENAI_API_KEY (optional, Enter to skip)"
create_secret "newsapi-key"       "NEWSAPI_KEY (optional, Enter to skip)"

echo "==> Creating the deployer service account (skips if it already exists)"
gcloud iam service-accounts create "${DEPLOYER_SA}" \
  --display-name="GitHub Actions Cloud Run deployer" \
  || echo "   (service account already exists, continuing)"

DEPLOYER_SA_EMAIL="${DEPLOYER_SA}@${PROJECT_ID}.iam.gserviceaccount.com"

echo "==> Granting the deployer SA the roles it needs to build/push/deploy"
for ROLE in roles/run.admin roles/artifactregistry.writer roles/iam.serviceAccountUser; do
  gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
    --member="serviceAccount:${DEPLOYER_SA_EMAIL}" \
    --role="${ROLE}" \
    --condition=None
done

echo "==> Letting Cloud Run's default runtime identity read the secrets"
PROJECT_NUMBER=$(gcloud projects describe "${PROJECT_ID}" --format='value(projectNumber)')
RUNTIME_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
for SECRET in anthropic-api-key openai-api-key newsapi-key; do
  gcloud secrets add-iam-policy-binding "${SECRET}" \
    --member="serviceAccount:${RUNTIME_SA}" \
    --role="roles/secretmanager.secretAccessor"
done

echo "==> Setting up Workload Identity Federation (keyless GitHub -> GCP auth)"
gcloud iam workload-identity-pools create "${WIF_POOL}" \
  --location="global" \
  --display-name="GitHub Actions pool" \
  || echo "   (pool already exists, continuing)"

gcloud iam workload-identity-pools providers create-oidc "${WIF_PROVIDER}" \
  --location="global" \
  --workload-identity-pool="${WIF_POOL}" \
  --display-name="GitHub OIDC provider" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository" \
  --attribute-condition="assertion.repository=='${GITHUB_REPO}'" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  || echo "   (provider already exists, continuing)"

WIF_POOL_ID=$(gcloud iam workload-identity-pools describe "${WIF_POOL}" --location=global --format='value(name)')

echo "==> Allowing GitHub Actions runs from ${GITHUB_REPO} to impersonate the deployer SA"
gcloud iam service-accounts add-iam-policy-binding "${DEPLOYER_SA_EMAIL}" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/${WIF_POOL_ID}/attribute.repository/${GITHUB_REPO}"

echo ""
echo "=================================================================="
echo "Done. Add these as GitHub repo secrets"
echo "(Settings -> Secrets and variables -> Actions -> New repository secret):"
echo ""
echo "GCP_WORKLOAD_IDENTITY_PROVIDER = ${WIF_POOL_ID}/providers/${WIF_PROVIDER}"
echo "GCP_SERVICE_ACCOUNT            = ${DEPLOYER_SA_EMAIL}"
echo "=================================================================="
