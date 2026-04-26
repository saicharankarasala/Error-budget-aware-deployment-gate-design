# CI/CD Notes

The active GitHub Actions workflow lives in `.github/workflows/deployment-gate.yml`.
This directory is kept as a portfolio-friendly place to review the pipeline source
and deployment safety contract outside GitHub's hidden workflow folder.

Required production secrets/variables:

- `PROMETHEUS_URL`: Prometheus or AMP query endpoint used by the burn-rate gate.
- `AWS_ROLE_TO_ASSUME`: IAM role created by `infra/aws` for GitHub OIDC deploys.
- `ECR_REPOSITORY_URL`: ECR repository URL created by Terraform.
- `AWS_REGION`: GitHub Actions variable, defaults to `us-east-1` when omitted.

