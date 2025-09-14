# Contributing to Prisma

We welcome contributions to Prisma! This document outlines how to contribute effectively to this AI-driven systematic literature review system.

## Table of Contents

- [Code of Conduct](#code-of-conduct)
- [Getting Started](#getting-started)
- [Development Workflow](#development-workflow)
- [Pull Request Process](#pull-request-process)
- [Coding Standards](#coding-standards)
- [Testing](#testing)
- [Documentation](#documentation)
- [Issue Reporting](#issue-reporting)
- [Security](#security)

## Code of Conduct

By participating in this project, you agree to abide by our [Code of Conduct](CODE_OF_CONDUCT.md). Please read it before contributing.

## Getting Started

### Prerequisites

Before contributing, please ensure you have:

- Read and understood the project [README](README.md)
- Reviewed the [GOVERNANCE](GOVERNANCE.md) document
- Set up your development environment according to the project requirements

### Development Setup

1. Fork the repository
2. Clone your fork: `git clone https://github.com/YOUR_USERNAME/prisma.git`
3. Add the upstream remote: `git remote add upstream https://github.com/CServinL/prisma.git`
4. Install dependencies (specific instructions will be added as the project evolves)

## Development Workflow

### Branching Strategy

We use a linear history approach with the following branch strategy:

- `main` - Production-ready code (protected)
- `feature/description` - Feature development branches
- `bugfix/description` - Bug fix branches
- `docs/description` - Documentation updates

### Branch Protection Rules

The `main` branch is protected with the following rules:
- Linear history required (no merge commits)
- Pull requests required for all changes
- Required signatures for commits
- No direct pushes to main
- All merge methods allowed (merge, squash, rebase)

## Pull Request Process

### Before Creating a PR

1. **Create an Issue**: For significant changes, create an issue first to discuss the approach
2. **Branch Naming**: Use descriptive branch names following the pattern: `type/short-description`
3. **Sync with Main**: Ensure your branch is up-to-date with the latest main branch
4. **Local Testing**: Run all tests and ensure they pass locally

### PR Requirements

1. **Clear Description**: Provide a clear description of what your PR does
2. **Issue Reference**: Link to related issues using `Fixes #issue-number` or `Closes #issue-number`
3. **Testing**: Include appropriate tests for new functionality
4. **Documentation**: Update relevant documentation
5. **Commit Messages**: Use clear, descriptive commit messages

### PR Template

```markdown
## Description
Brief description of the changes

## Type of Change
- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Documentation update

## Testing
- [ ] Tests pass locally
- [ ] New tests added for new functionality
- [ ] Manual testing completed

## Related Issues
Fixes #(issue number)

## Additional Notes
Any additional information or context
```

### Review Process

1. **Automated Checks**: All automated checks must pass
2. **Code Review**: At least one maintainer review required
3. **Conversation Resolution**: All review conversations must be resolved
4. **Final Approval**: Maintainer approval required before merge

## Coding Standards

### General Principles

- **Clarity over Cleverness**: Write clear, readable code
- **Consistency**: Follow existing code patterns and conventions
- **Documentation**: Document complex logic and public APIs
- **Error Handling**: Implement proper error handling and logging

### Python (when applicable)

- Follow PEP 8 style guidelines
- Use type hints for function signatures
- Maximum line length: 88 characters (Black formatter)
- Use docstrings for all public functions and classes

### JavaScript/TypeScript (when applicable)

- Follow ESLint configuration
- Use TypeScript for type safety
- Prefer functional programming patterns
- Use meaningful variable and function names

### Configuration Files

- Use YAML for human-readable configuration
- JSON for structured data exchange
- Include schema validation where appropriate

## Testing

### Testing Strategy

- **Unit Tests**: Test individual components in isolation
- **Integration Tests**: Test component interactions
- **End-to-End Tests**: Test complete workflows
- **Performance Tests**: Test system performance under load

### Test Requirements

- All new functionality must include tests
- Maintain or improve test coverage
- Tests should be deterministic and isolated
- Include both positive and negative test cases

## Documentation

### Documentation Standards

- **README**: Keep project overview current
- **API Documentation**: Document all public APIs
- **Configuration**: Document all configuration options
- **Examples**: Provide working examples
- **Architecture**: Document system design decisions

### Documentation Updates

- Update documentation for any new features
- Include examples for complex functionality
- Keep installation and setup instructions current
- Update version compatibility information

## Issue Reporting

### Bug Reports

When reporting bugs, please include:

- **Environment**: OS, Python version, dependencies
- **Steps to Reproduce**: Clear steps to reproduce the issue
- **Expected Behavior**: What you expected to happen
- **Actual Behavior**: What actually happened
- **Error Messages**: Full error messages and stack traces
- **Configuration**: Relevant configuration details

### Feature Requests

For feature requests, please include:

- **Use Case**: Describe the problem you're trying to solve
- **Proposed Solution**: Your suggested approach
- **Alternatives**: Other approaches you've considered
- **Impact**: Who would benefit from this feature

### Issue Labels

We use the following labels to categorize issues:

- `bug` - Something isn't working
- `enhancement` - New feature or request
- `documentation` - Improvements or additions to documentation
- `good first issue` - Good for newcomers
- `help wanted` - Extra attention is needed
- `priority: high/medium/low` - Issue priority
- `status: in-progress` - Currently being worked on

## Security

### Security Issues

- **Do not** open public issues for security vulnerabilities
- Follow our [Security Policy](SECURITY.md) for reporting
- Use private communication channels for sensitive issues

### Secure Coding Practices

- Validate all inputs
- Use secure authentication and authorization
- Follow the principle of least privilege
- Keep dependencies up to date
- Use environment variables for sensitive configuration

## Getting Help

### Communication Channels

- **GitHub Issues**: For bugs, features, and general discussion
- **GitHub Discussions**: For questions and community interaction
- **Email**: For security issues and private matters

### Maintainer Contact

Current maintainers:
- @CServinL - Project Lead

## Recognition

Contributors will be recognized in:
- Repository contributors list
- Release notes for significant contributions
- Project documentation where appropriate

## License

By contributing to Prisma, you agree that your contributions will be licensed under the same [Apache 2.0 License](LICENSE) that covers the project.

---

Thank you for contributing to Prisma! Your efforts help make systematic literature review more accessible and efficient for the research community.