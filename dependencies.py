import subprocess
import sys
import importlib.util

def check_module_installed(module_name):
    """Check if a module is installed."""
    return importlib.util.find_spec(module_name) is not None

def install_package(package_name):
    """Install a package using pip."""
    subprocess.check_call([sys.executable, "-m", "pip", "install", package_name])
    print(f"Successfully installed {package_name}")

def check_and_install_dependencies():
    """Check and install required dependencies if needed."""
    required_packages = {
        "pytube": "pytube",
        "tkinter": "tk",
        "PIL": "pillow"
    }
    
    packages_to_install = []
    
    # Check for each required package
    for module_name, package_name in required_packages.items():
        if module_name == "tkinter":
            try:
                import tkinter
            except ImportError:
                packages_to_install.append(package_name)
        elif not check_module_installed(module_name):
            packages_to_install.append(package_name)
    
    # Install missing packages
    if packages_to_install:
        print("Installing missing dependencies...")
        for package in packages_to_install:
            try:
                install_package(package)
            except Exception as e:
                print(f"Error installing {package}: {e}")
                sys.exit(1)
        print("All dependencies installed successfully.")
    else:
        print("All required dependencies are already installed.")
