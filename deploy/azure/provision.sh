#!/usr/bin/env bash
# Creates the Azure resources for AEON ingest. Run it in Azure Cloud Shell (Bash) or anywhere the
# Azure CLI is installed and `az login` has been done. Safe to re-run: existing resources are kept.
#
#   bash deploy/azure/provision.sh
#
# Override defaults with environment variables, e.g.  LOCATION=westeurope VM_SIZE=Standard_B2ms bash provision.sh
set -euo pipefail

RG="${RG:-aeon-rg}"
LOCATION="${LOCATION:-eastus}"            # close to the SPHEREx S3 bucket (AWS us-east-1)
VM_NAME="${VM_NAME:-aeon-ingest}"
VM_SIZE="${VM_SIZE:-Standard_B2s}"        # 2 vCPU / 4 GB
ADMIN_USER="${ADMIN_USER:-aeon}"
CONTAINER="${CONTAINER:-aeon-data}"
DATA_DISK_GB="${DATA_DISK_GB:-64}"
SUB_ID="$(az account show --query id -o tsv)"
# Storage account names are global: 3-24 lower-case letters/digits. Derived from the subscription
# so re-runs reuse the same account.
STORAGE="${STORAGE:-aeon$(echo -n "$SUB_ID" | sha1sum | cut -c1-12)}"

say() { printf '\n\033[1m==> %s\033[0m\n' "$*"; }

say "Subscription: $(az account show --query name -o tsv) ($SUB_ID)"
say "Resource group $RG in $LOCATION"
az group create -n "$RG" -l "$LOCATION" -o none

say "Storage account $STORAGE (no shared-key access: identities only)"
if ! az storage account show -n "$STORAGE" -g "$RG" -o none 2>/dev/null; then
  az storage account create -n "$STORAGE" -g "$RG" -l "$LOCATION" \
    --sku Standard_LRS --kind StorageV2 --min-tls-version TLS1_2 \
    --allow-blob-public-access false --allow-shared-key-access false -o none
fi
STORAGE_ID="$(az storage account show -n "$STORAGE" -g "$RG" --query id -o tsv)"

say "VM $VM_NAME ($VM_SIZE, Ubuntu 24.04, system-assigned managed identity, ${DATA_DISK_GB} GB data disk)"
if ! az vm show -g "$RG" -n "$VM_NAME" -o none 2>/dev/null; then
  az vm create -g "$RG" -n "$VM_NAME" -l "$LOCATION" \
    --image Ubuntu2404 --size "$VM_SIZE" \
    --admin-username "$ADMIN_USER" --generate-ssh-keys \
    --assign-identity --data-disk-sizes-gb "$DATA_DISK_GB" \
    --public-ip-sku Standard --nsg-rule SSH -o none
fi
PRINCIPAL_ID="$(az vm show -g "$RG" -n "$VM_NAME" --query identity.principalId -o tsv)"

say "Role: the VM may write blobs in $STORAGE (Storage Blob Data Contributor)"
az role assignment create --assignee-object-id "$PRINCIPAL_ID" --assignee-principal-type ServicePrincipal \
  --role "Storage Blob Data Contributor" --scope "$STORAGE_ID" -o none 2>/dev/null || true

say "Role: you may read the blobs in the portal (Storage Blob Data Reader)"
ME="$(az ad signed-in-user show --query id -o tsv 2>/dev/null || true)"
if [ -n "$ME" ]; then
  az role assignment create --assignee-object-id "$ME" --assignee-principal-type User \
    --role "Storage Blob Data Reader" --scope "$STORAGE_ID" -o none 2>/dev/null || true
fi

IP="$(az vm show -d -g "$RG" -n "$VM_NAME" --query publicIps -o tsv)"
cat <<EOF

Done.
  VM public IP       : $IP
  SSH                : ssh $ADMIN_USER@$IP
  Blob account URL   : https://$STORAGE.blob.core.windows.net
  Blob container     : $CONTAINER

Next (on the VM, see deploy/azure/README.md step 3):
  ssh $ADMIN_USER@$IP
  git clone https://github.com/alpztel/aeon.git
  sudo BLOB_ACCOUNT_URL=https://$STORAGE.blob.core.windows.net bash aeon/deploy/azure/setup-vm.sh
EOF
