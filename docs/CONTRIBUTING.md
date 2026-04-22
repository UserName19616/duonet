# Contributing to DuoNet

Thank you for your interest in DuoNet! This is a community-driven project, and every contribution matters.

## How to Contribute

1. **Fork the repository** on GitHub
2. **Create a feature branch** (`git checkout -b feature/amazing-feature`)
3. **Commit your changes** (`git commit -m 'Add amazing feature'`)
4. **Push to the branch** (`git push origin feature/amazing-feature`)
5. **Open a Pull Request**

## Development Setup

```bash
git clone https://github.com/YOUR_USERNAME/duonet.git
cd duonet
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
./install.sh
./run_web.sh
Code Style
Python
Follow PEP 8

Use type hints for all function signatures

Maximum line length: 100 characters

Docstrings for all public functions

JavaScript
Use modern ES6+ features

Avoid jQuery

Use const and let, never var

Comment complex logic

Commit Messages
text
feat: add new feature
fix: correct bug in rotation manager
docs: update README
test: add unit tests for crypto
refactor: reorganize message router
Testing
bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/unit/test_crypto_aes.py -v

# Run with coverage
pytest --cov=src tests/
Pull Request Checklist
Code follows style guidelines

Tests added for new features

All tests pass

Documentation updated

No breaking changes without discussion

Reporting Bugs
Use GitHub Issues with the following template:

markdown
**Describe the bug**
A clear description of what the bug is.

**To Reproduce**
Steps to reproduce the behavior.

**Expected behavior**
What you expected to happen.

**Screenshots**
If applicable.

**Environment:**
- OS: [e.g., Ubuntu 22.04]
- Python version: [e.g., 3.10]
- Browser (if web issue): [e.g., Chrome 120]

**Additional context**
Add any other context here.
Feature Requests
Open an issue with the label enhancement and describe:

What problem does this solve?

How would it work?

Are there any alternatives?

Questions?
Contact the author: leha.nikolaev@gmail.com

Thank you for contributing to free, decentralized communication!
