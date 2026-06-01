# Security Policy

## Public Repository Notice

This repository is a sanitized public version. Production secrets, API keys, deployment scripts, and private infrastructure configuration are intentionally excluded.

## Reporting Vulnerabilities

Report security issues privately to the maintainers. Do not open public issues for security vulnerabilities.

## Secrets Management

- Never commit `.env`, `config/api_keys.json`, or other secret files
- Use environment variables for all credentials
- Rotate API keys regularly
- Use separate keys for different environments

## Production Security

- Admin endpoints require `ADMIN_API_TOKEN`
- API keys are masked in all responses
- Rate limiting on admin endpoints
- File permissions: `chmod 600` on config files

## Dependencies

- Regularly update dependencies
- Monitor for security advisories
- Use pinned versions in `requirements.txt`
