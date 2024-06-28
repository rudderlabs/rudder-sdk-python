# setup_env.sh
# Clean up temporarary directories
rm -rf build
rm -rf dist
rm -rf rudder_sdk_python.egg-info

# Ensure pip is updated
pip install --upgrade pip

# Install extra dependencies
# Use specific versions to avoid conflicts
pip install pip-tools==7.4.1 setuptools==70.1.1 wheel==0.43.0 twine==5.1.1

# Install project dependencies
pip install -r requirements.txt
