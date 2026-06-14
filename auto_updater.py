#!/usr/bin/env python3
"""
Auto-updater module for Neural Extractor.

This module provides functionality to automatically update the app's dependencies
from requirements.txt. It includes:

- Checking for outdated packages using pip list --outdated
- Safely upgrading outdated packages
- Logging all actions and errors
- Cross-platform compatibility (Windows, Linux, macOS)
- Backup of requirements.txt before updating
- Integration with app state to skip updates during active downloads
"""

import logging
import shutil
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path


class AutoUpdater:
    """Auto-updater for managing package dependencies."""

    def __init__(self, requirements_file="requirements.txt", log_file="logs/auto-updater.log"):
        """
        Initialize the AutoUpdater.

        Args:
            requirements_file (str): Path to requirements.txt
            log_file (str): Path to log file
        """
        self.requirements_file = Path(requirements_file)
        self.log_file = Path(log_file)
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self.is_updating = False
        self._lock = threading.Lock()

        # Setup logging
        self._setup_logging()

        self.logger.info("Auto-updater initialized")

    def _setup_logging(self):
        """Configure logging to file."""
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s - %(levelname)s - %(message)s",
            handlers=[
                logging.FileHandler(self.log_file, encoding="utf-8"),
                logging.StreamHandler(),  # Also log to console
            ],
        )
        self.logger = logging.getLogger(__name__)

    def is_task_in_progress(self):
        """
        Check if a download/conversion task is currently in progress.

        This should be overridden or passed as a callback in the main app.

        Returns:
            bool: True if task is in progress
        """
        # Default implementation - should be set by the main app
        return False

    def backup_requirements(self):
        """
        Create a backup of requirements.txt before updating.

        Returns:
            Path: Path to the backup file, or None if backup failed
        """
        try:
            if not self.requirements_file.exists():
                self.logger.warning(f"Requirements file not found: {self.requirements_file}")
                return None

            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup_file = self.requirements_file.with_suffix(f".{timestamp}.backup")
            shutil.copy2(self.requirements_file, backup_file)
            self.logger.info(f"Backed up requirements.txt to {backup_file}")
            return backup_file
        except Exception as e:
            self.logger.error(f"Failed to backup requirements.txt: {e}")
            return None

    def get_outdated_packages(self):
        """
        Get list of outdated packages using pip list --outdated.

        Returns:
            list: List of tuples (package_name, current_version, latest_version)
        """
        try:
            self.logger.info("Checking for outdated packages...")

            # Run pip list --outdated
            result = subprocess.run(
                [sys.executable, "-m", "pip", "list", "--outdated", "--format=json"],
                capture_output=True,
                text=True,
                timeout=60,
            )

            if result.returncode != 0:
                self.logger.error(f"Failed to check outdated packages: {result.stderr}")
                return []

            # Parse JSON output
            import json

            outdated_data = json.loads(result.stdout)

            packages = []
            for package in outdated_data:
                packages.append(
                    (
                        package["name"],
                        package.get("version", "unknown"),
                        package.get("latest_version", "unknown"),
                    )
                )

            if packages:
                self.logger.info(f"Found {len(packages)} outdated packages")
                for name, current, latest in packages:
                    self.logger.info(f"  {name}: {current} -> {latest}")
            else:
                self.logger.info("All packages are up to date")

            return packages

        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse pip output: {e}")
            return []
        except subprocess.TimeoutExpired:
            self.logger.error("Timeout while checking for outdated packages")
            return []
        except Exception as e:
            self.logger.error(f"Error checking for outdated packages: {e}")
            return []

    def update_package(self, package_name, package_spec):
        """
        Update a single package.

        Args:
            package_name (str): Name of the package
            package_spec (str): Package specification (may include version)

        Returns:
            bool: True if update was successful
        """
        try:
            self.logger.info(f"Updating {package_name}...")

            result = subprocess.run(
                [sys.executable, "-m", "pip", "install", "--upgrade", package_spec],
                capture_output=True,
                text=True,
                timeout=300,  # 5 minute timeout
            )

            if result.returncode == 0:
                self.logger.info(f"Successfully updated {package_name}")
                return True
            else:
                self.logger.error(f"Failed to update {package_name}: {result.stderr}")
                return False

        except subprocess.TimeoutExpired:
            self.logger.error(f"Timeout while updating {package_name}")
            return False
        except Exception as e:
            self.logger.error(f"Error updating {package_name}: {e}")
            return False

    def parse_requirements(self):
        """
        Parse requirements.txt to get package specifications.

        Returns:
            dict: Dictionary mapping package names to their specifications
        """
        packages = {}

        try:
            if not self.requirements_file.exists():
                self.logger.warning(f"Requirements file not found: {self.requirements_file}")
                return packages

            with open(self.requirements_file, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue

                    # Extract package name (before first operator)
                    name = (
                        line.split(">=")[0]
                        .split("==")[0]
                        .split("<=")[0]
                        .split("!=")[0]
                        .split(">")[0]
                        .split("<")[0]
                        .strip()
                    )
                    packages[name] = line

            self.logger.info(f"Parsed {len(packages)} packages from requirements.txt")
            return packages

        except Exception as e:
            self.logger.error(f"Error parsing requirements.txt: {e}")
            return {}

    def update_requirements_file(self, outdated_packages):
        """
        Update requirements.txt with latest versions.

        Args:
            outdated_packages (list): List of tuples (name, current, latest)

        Returns:
            bool: True if update was successful
        """
        try:
            if not self.requirements_file.exists():
                self.logger.warning("Requirements file not found, skipping update")
                return False

            # Parse current requirements
            packages = self.parse_requirements()

            # Update with latest versions
            updated = False
            with open(self.requirements_file, "w", encoding="utf-8") as f:
                for name, spec in packages.items():
                    # Check if this package is outdated
                    for outdated_name, _, latest_version in outdated_packages:
                        if name == outdated_name:
                            # Update to latest version
                            f.write(f"{name}>={latest_version}\n")
                            self.logger.info(f"Updated {name} to >= {latest_version}")
                            updated = True
                            break
                    else:
                        # Keep original specification
                        f.write(f"{spec}\n")

            if updated:
                self.logger.info("Updated requirements.txt with latest versions")

            return updated

        except Exception as e:
            self.logger.error(f"Error updating requirements.txt: {e}")
            return False

    def run_auto_update(self, update_file=True):
        """
        Run automatic update process.

        Args:
            update_file (bool): Whether to update requirements.txt file

        Returns:
            dict: Update results with status and details
        """
        with self._lock:
            if self.is_updating:
                self.logger.warning("Update already in progress, skipping")
                return {"status": "skipped", "message": "Update already in progress"}

            if self.is_task_in_progress():
                self.logger.info("Task in progress, skipping auto-update")
                return {"status": "skipped", "message": "Task in progress"}

            self.is_updating = True
            self.logger.info("Starting auto-update process")

        try:
            # Get list of outdated packages
            outdated_packages = self.get_outdated_packages()

            if not outdated_packages:
                return {
                    "status": "up_to_date",
                    "message": "All packages are up to date",
                    "packages_updated": 0,
                }

            # Backup requirements.txt
            backup_file = self.backup_requirements()

            # Update packages
            updated_count = 0
            failed_packages = []

            packages = self.parse_requirements()

            for package_name, _, _ in outdated_packages:
                if self.is_task_in_progress():
                    self.logger.warning("Task started during update, stopping")
                    failed_packages.append(package_name)
                    continue

                # Get package specification
                package_spec = packages.get(package_name, package_name)

                if self.update_package(package_name, package_spec):
                    updated_count += 1
                else:
                    failed_packages.append(package_name)

            # Update requirements.txt if requested and successful
            if update_file and updated_count > 0 and not self.is_task_in_progress():
                self.update_requirements_file(outdated_packages)

            result = {
                "status": "completed" if updated_count > 0 else "partial",
                "message": f"Updated {updated_count} packages",
                "packages_updated": updated_count,
                "packages_total": len(outdated_packages),
                "failed_packages": failed_packages,
                "backup_file": str(backup_file) if backup_file else None,
            }

            self.logger.info(
                f"Update complete: {updated_count}/{len(outdated_packages)} packages updated"
            )

            if failed_packages:
                self.logger.warning(f"Failed to update packages: {failed_packages}")

            return result

        except Exception as e:
            self.logger.error(f"Error during auto-update: {e}")
            return {"status": "error", "message": f"Error during update: {str(e)}"}
        finally:
            self.is_updating = False

    def check_for_updates(self):
        """
        Check for available updates without installing them.

        Returns:
            list: List of tuples (package_name, current_version, latest_version)
        """
        try:
            self.logger.info("Checking for available updates...")
            outdated_packages = self.get_outdated_packages()

            return outdated_packages

        except Exception as e:
            self.logger.error(f"Error checking for updates: {e}")
            return []


def create_updater_with_callback(
    requirements_file="requirements.txt",
    log_file="logs/auto-updater.log",
    task_in_progress_callback=None,
):
    """
    Factory function to create an AutoUpdater with custom task callback.

    Args:
        requirements_file (str): Path to requirements.txt
        log_file (str): Path to log file
        task_in_progress_callback (callable): Function to check if task is in progress

    Returns:
        AutoUpdater: Configured updater instance
    """
    updater = AutoUpdater(requirements_file, log_file)

    if task_in_progress_callback:
        updater.is_task_in_progress = task_in_progress_callback

    return updater


if __name__ == "__main__":
    # Test the auto-updater
    print("Testing Auto-Updater...")

    updater = AutoUpdater()

    # Check for updates
    outdated = updater.check_for_updates()

    if outdated:
        print(f"Found {len(outdated)} outdated packages:")
        for name, current, latest in outdated:
            print(f"  {name}: {current} -> {latest}")
    else:
        print("All packages are up to date")

    # Run auto-update (commented out to prevent accidental updates)
    # result = updater.run_auto_update()
    # print(f"Update result: {result}")
