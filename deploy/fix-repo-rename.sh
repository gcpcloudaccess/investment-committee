#!/usr/bin/env bash
# One-time fix for the GitHub repo rename (investment-committee -> money-minting-machine).
# The WIF provider's attribute-condition and the deployer SA's IAM binding were
# both still pointing at the OLD repo name, so GitHub's OIDC token (which now
# says repository=gcpcloudaccess/money-minting-machine) no longer matched and
# got rejected. This updates both to the new name.
#
# Run this yourself (not via Claude) - same reasoning as setup-gcp.sh: it
# modifies who can authenticate as your deployer service account.
set -euo pipefail

PROJECT_ID="money-minting-machine"
OLD_REPO="gcpcloudaccess/investment-committee"
NEW_REPO="gcpcloudaccess/money-minting-machine"
DEPLOYER_SA="github-deployer@${PROJECT_ID}.iam.gserviceaccount.com"
WIF_POOL="github-pool"
WIF_PROVIDER="github-provider"

gcloud config set project "${PROJECT_ID}"

echo "==> Updating WIF provider's attribute-condition to trust ${NEW_REPO}"
gcloud iam workload-identity-pools providers update-oidc "${WIF_PROVIDER}" \
  --location="global" \
  --workload-identity-pool="${WIF_POOL}" \
  --attribute-condition="assertion.repository=='${NEW_REPO}'"

WIF_POOL_ID=$(gcloud iam workload-identity-pools describe "${WIF_POOL}" --location=global --format='value(name)')

echo "==> Removing the old repo's impersonation binding"
gcloud iam service-accounts remove-iam-policy-binding "${DEPLOYER_SA}" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/${WIF_POOL_ID}/attribute.repository/${OLD_REPO}" \
  || echo "   (binding didn't exist under that exact name, continuing)"

echo "==> Adding the new repo's impersonation binding"
gcloud iam service-accounts add-iam-policy-binding "${DEPLOYER_SA}" \
  --role="roles/iam.workloadIdentityUser" \
  --member="principalSet://iam.googleapis.com/${WIF_POOL_ID}/attribute.repository/${NEW_REPO}"

echo ""
echo "Done. Secret values in GitHub are unchanged - only the trust relationship moved to the new repo name."