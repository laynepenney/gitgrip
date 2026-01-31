#!/bin/bash
#
# Azure DevOps Test Repository Setup Script
#
# Creates test repositories in Azure DevOps for gitgrip e2e testing.
# These repos are used to verify Azure DevOps platform integration.
#
# Prerequisites:
#   - Azure CLI installed (az)
#   - Logged in to Azure (az login)
#   - Azure DevOps extension installed (az extension add --name azure-devops)
#   - AZURE_DEVOPS_ORG and AZURE_DEVOPS_PROJECT environment variables set
#
# Usage:
#   export AZURE_DEVOPS_ORG=myorg
#   export AZURE_DEVOPS_PROJECT=myproject
#   ./scripts/azure-test-setup.sh [create|delete|status]
#

set -e

# Color output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Test repo names
REPO_FRONTEND="gitgrip-test-frontend"
REPO_BACKEND="gitgrip-test-backend"
REPO_SHARED="gitgrip-test-shared"

# Check required environment variables
check_env() {
    if [ -z "$AZURE_DEVOPS_ORG" ]; then
        echo -e "${RED}Error: AZURE_DEVOPS_ORG not set${NC}"
        echo "Set it with: export AZURE_DEVOPS_ORG=your-org"
        exit 1
    fi

    if [ -z "$AZURE_DEVOPS_PROJECT" ]; then
        echo -e "${RED}Error: AZURE_DEVOPS_PROJECT not set${NC}"
        echo "Set it with: export AZURE_DEVOPS_PROJECT=your-project"
        exit 1
    fi

    echo -e "${GREEN}Using Azure DevOps:${NC}"
    echo "  Organization: $AZURE_DEVOPS_ORG"
    echo "  Project: $AZURE_DEVOPS_PROJECT"
    echo
}

# Check if az cli is installed and logged in
check_azure_cli() {
    if ! command -v az &> /dev/null; then
        echo -e "${RED}Error: Azure CLI (az) not found${NC}"
        echo "Install from: https://docs.microsoft.com/en-us/cli/azure/install-azure-cli"
        exit 1
    fi

    # Check if logged in
    if ! az account show &> /dev/null; then
        echo -e "${RED}Error: Not logged in to Azure${NC}"
        echo "Run: az login"
        exit 1
    fi

    # Check if devops extension is installed
    if ! az extension show --name azure-devops &> /dev/null; then
        echo -e "${YELLOW}Installing Azure DevOps extension...${NC}"
        az extension add --name azure-devops
    fi

    # Configure default organization and project
    az devops configure --defaults organization="https://dev.azure.com/$AZURE_DEVOPS_ORG" project="$AZURE_DEVOPS_PROJECT"
}

# Create a test repository
create_repo() {
    local repo_name=$1
    local description=$2

    echo -n "Creating repository '$repo_name'... "

    # Check if repo already exists
    if az repos show --repository "$repo_name" &> /dev/null; then
        echo -e "${YELLOW}already exists${NC}"
        return 0
    fi

    # Create the repo
    if az repos create --name "$repo_name" --output none; then
        echo -e "${GREEN}created${NC}"

        # Initialize with a README
        local clone_url
        clone_url=$(az repos show --repository "$repo_name" --query sshUrl -o tsv)

        # Create a temp directory and initialize the repo
        local temp_dir
        temp_dir=$(mktemp -d)
        cd "$temp_dir"

        git init -q
        echo "# $repo_name" > README.md
        echo "" >> README.md
        echo "$description" >> README.md
        git add README.md
        git commit -q -m "Initial commit"

        # Push to Azure DevOps
        git remote add origin "$clone_url"
        if git push -u origin main 2>/dev/null || git push -u origin master 2>/dev/null; then
            echo "  Initialized with README"
        else
            echo -e "  ${YELLOW}Warning: Could not push initial commit${NC}"
        fi

        cd - > /dev/null
        rm -rf "$temp_dir"
    else
        echo -e "${RED}failed${NC}"
        return 1
    fi
}

# Delete a test repository
delete_repo() {
    local repo_name=$1

    echo -n "Deleting repository '$repo_name'... "

    # Check if repo exists
    if ! az repos show --repository "$repo_name" &> /dev/null; then
        echo -e "${YELLOW}does not exist${NC}"
        return 0
    fi

    # Delete the repo
    if az repos delete --id "$repo_name" --yes --output none; then
        echo -e "${GREEN}deleted${NC}"
    else
        echo -e "${RED}failed${NC}"
        return 1
    fi
}

# Show status of test repositories
show_status() {
    echo "Test Repository Status:"
    echo

    for repo in $REPO_FRONTEND $REPO_BACKEND $REPO_SHARED; do
        echo -n "  $repo: "
        if az repos show --repository "$repo" &> /dev/null; then
            local url
            url=$(az repos show --repository "$repo" --query webUrl -o tsv)
            echo -e "${GREEN}exists${NC} - $url"
        else
            echo -e "${YELLOW}not found${NC}"
        fi
    done
}

# Print usage
usage() {
    echo "Usage: $0 [command]"
    echo
    echo "Commands:"
    echo "  create  - Create test repositories"
    echo "  delete  - Delete test repositories"
    echo "  status  - Show status of test repositories"
    echo
    echo "Environment Variables:"
    echo "  AZURE_DEVOPS_ORG     - Azure DevOps organization name"
    echo "  AZURE_DEVOPS_PROJECT - Azure DevOps project name"
    echo
    echo "Example:"
    echo "  export AZURE_DEVOPS_ORG=myorg"
    echo "  export AZURE_DEVOPS_PROJECT=myproject"
    echo "  $0 create"
}

# Main
main() {
    local command=${1:-status}

    check_env
    check_azure_cli

    case $command in
        create)
            echo "Creating test repositories..."
            echo
            create_repo "$REPO_FRONTEND" "Frontend test repository for gitgrip e2e testing"
            create_repo "$REPO_BACKEND" "Backend test repository for gitgrip e2e testing"
            create_repo "$REPO_SHARED" "Shared library test repository for gitgrip e2e testing"
            echo
            echo -e "${GREEN}Setup complete!${NC}"
            echo
            echo "You can now run integration tests with:"
            echo "  export AZURE_DEVOPS_TOKEN=\$(az account get-access-token --resource 499b84ac-1321-427f-aa17-267ca6975798 --query accessToken -o tsv)"
            echo "  cargo test --features integration-tests -- --ignored test_azure"
            ;;
        delete)
            echo "Deleting test repositories..."
            echo
            delete_repo "$REPO_FRONTEND"
            delete_repo "$REPO_BACKEND"
            delete_repo "$REPO_SHARED"
            echo
            echo -e "${GREEN}Cleanup complete!${NC}"
            ;;
        status)
            show_status
            ;;
        help|--help|-h)
            usage
            ;;
        *)
            echo -e "${RED}Unknown command: $command${NC}"
            echo
            usage
            exit 1
            ;;
    esac
}

main "$@"
