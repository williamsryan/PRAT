"""
Docker orchestration module for PRAT.

This module provides functions to build Docker images and run containers
for reproducible PRAT analysis workflows.
"""

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class ContainerResult:
    """Result of Docker container execution."""
    success: bool
    exit_code: int
    stdout: str
    stderr: str
    container_id: Optional[str] = None
    error_message: Optional[str] = None


def check_docker_available() -> bool:
    """
    Check if Docker is available on the system.

    Returns:
        True if Docker is available, False otherwise
    """
    try:
        result = subprocess.run(
            ["docker", "--version"],
            capture_output=True,
            text=True,
            timeout=5
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def build_docker_image(
    dockerfile_path: str,
    image_name: str,
    build_context: Optional[str] = None,
    build_args: Optional[dict[str, str]] = None,
    no_cache: bool = False
) -> bool:
    """
    Build Docker image from Dockerfile.

    Args:
        dockerfile_path: Path to Dockerfile
        image_name: Name and tag for the image (e.g., "prat-demo:mosquitto-tls")
        build_context: Build context directory (default: directory containing Dockerfile)
        build_args: Build arguments to pass to Docker build
        no_cache: If True, build without using cache

    Returns:
        True if build successful, False otherwise
    """
    dockerfile = Path(dockerfile_path)

    if not dockerfile.exists():
        print(f"[!] Dockerfile not found: {dockerfile_path}")
        return False

    if not check_docker_available():
        print("[!] Docker is not available on this system")
        print("[!] Please install Docker: https://docs.docker.com/get-docker/")
        return False

    # Use directory containing Dockerfile as build context if not specified
    if build_context is None:
        build_context = str(dockerfile.parent)

    print(f"\n{'='*70}")
    print(f"Building Docker Image: {image_name}")
    print(f"{'='*70}")
    print(f"Dockerfile: {dockerfile_path}")
    print(f"Build context: {build_context}")

    # Build docker command
    cmd = [
        "docker", "build",
        "-f", str(dockerfile),
        "-t", image_name
    ]

    # Add build arguments
    if build_args:
        for key, value in build_args.items():
            cmd.extend(["--build-arg", f"{key}={value}"])
            print(f"Build arg: {key}={value}")

    # Add no-cache flag
    if no_cache:
        cmd.append("--no-cache")
        print("No cache: enabled")

    cmd.append(build_context)

    print(f"\nRunning: {' '.join(cmd)}\n")

    try:
        # Run docker build with real-time output
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1
        )

        # Stream output
        for line in process.stdout:
            print(line, end='')

        process.wait()

        if process.returncode == 0:
            print(f"\n[+] Successfully built image: {image_name}")
            return True
        else:
            print(f"\n[!] Docker build failed with exit code {process.returncode}")
            return False

    except subprocess.TimeoutExpired:
        print("\n[!] Docker build timed out")
        return False
    except Exception as e:
        print(f"\n[!] Docker build error: {e}")
        return False


def run_docker_container(
    image_name: str,
    container_name: Optional[str] = None,
    volumes: Optional[dict[str, str]] = None,
    environment: Optional[dict[str, str]] = None,
    command: Optional[list[str]] = None,
    remove: bool = True,
    detach: bool = False,
    timeout: Optional[int] = None
) -> ContainerResult:
    """
    Run Docker container and return results.

    Args:
        image_name: Name of Docker image to run
        container_name: Optional name for the container
        volumes: Dictionary mapping host paths to container paths
        environment: Environment variables to set in container
        command: Command to run in container (overrides CMD in Dockerfile)
        remove: If True, automatically remove container when it exits
        detach: If True, run container in background
        timeout: Maximum time to wait for container (seconds)

    Returns:
        ContainerResult with output and exit code
    """
    if not check_docker_available():
        return ContainerResult(
            success=False,
            exit_code=-1,
            stdout="",
            stderr="",
            error_message="Docker is not available on this system"
        )

    print(f"\n{'='*70}")
    print(f"Running Docker Container: {image_name}")
    print(f"{'='*70}")

    # Build docker run command
    cmd = ["docker", "run"]

    # Add container name
    if container_name:
        cmd.extend(["--name", container_name])
        print(f"Container name: {container_name}")

    # Add volumes
    if volumes:
        for host_path, container_path in volumes.items():
            cmd.extend(["-v", f"{host_path}:{container_path}"])
            print(f"Volume: {host_path} -> {container_path}")

    # Add environment variables
    if environment:
        for key, value in environment.items():
            cmd.extend(["-e", f"{key}={value}"])
            print(f"Environment: {key}={value}")

    # Add remove flag
    if remove:
        cmd.append("--rm")

    # Add detach flag
    if detach:
        cmd.append("-d")

    # Add image name
    cmd.append(image_name)

    # Add command
    if command:
        cmd.extend(command)
        print(f"Command: {' '.join(command)}")

    print(f"\nRunning: {' '.join(cmd)}\n")

    try:
        # Run container
        if detach:
            # Detached mode - just start and return container ID
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout
            )

            if result.returncode == 0:
                container_id = result.stdout.strip()
                print(f"[+] Container started: {container_id}")
                return ContainerResult(
                    success=True,
                    exit_code=0,
                    stdout=result.stdout,
                    stderr=result.stderr,
                    container_id=container_id
                )
            else:
                print("[!] Failed to start container")
                return ContainerResult(
                    success=False,
                    exit_code=result.returncode,
                    stdout=result.stdout,
                    stderr=result.stderr,
                    error_message="Failed to start container"
                )
        else:
            # Attached mode - stream output
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )

            stdout_lines = []
            stderr_lines = []

            # Stream stdout
            for line in process.stdout:
                print(line, end='')
                stdout_lines.append(line)

            # Wait for completion
            process.wait(timeout=timeout)

            # Capture stderr
            stderr = process.stderr.read()
            if stderr:
                print(stderr, end='')
                stderr_lines.append(stderr)

            stdout = ''.join(stdout_lines)
            stderr = ''.join(stderr_lines)

            if process.returncode == 0:
                print("\n[+] Container completed successfully")
                return ContainerResult(
                    success=True,
                    exit_code=0,
                    stdout=stdout,
                    stderr=stderr
                )
            else:
                print(f"\n[!] Container failed with exit code {process.returncode}")
                return ContainerResult(
                    success=False,
                    exit_code=process.returncode,
                    stdout=stdout,
                    stderr=stderr,
                    error_message=f"Container exited with code {process.returncode}"
                )

    except subprocess.TimeoutExpired:
        error_msg = f"Container execution timed out after {timeout}s"
        print(f"\n[!] {error_msg}")
        return ContainerResult(
            success=False,
            exit_code=-1,
            stdout="",
            stderr="",
            error_message=error_msg
        )
    except Exception as e:
        error_msg = f"Container execution error: {e}"
        print(f"\n[!] {error_msg}")
        return ContainerResult(
            success=False,
            exit_code=-1,
            stdout="",
            stderr="",
            error_message=error_msg
        )


def list_docker_images(filter_name: Optional[str] = None) -> list[dict[str, str]]:
    """
    List Docker images on the system.

    Args:
        filter_name: Optional filter for image names

    Returns:
        List of dictionaries with image information
    """
    if not check_docker_available():
        return []

    cmd = ["docker", "images", "--format", "{{json .}}"]

    if filter_name:
        cmd.extend(["--filter", f"reference={filter_name}"])

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=10
        )

        if result.returncode != 0:
            return []

        images = []
        for line in result.stdout.strip().split('\n'):
            if line:
                images.append(json.loads(line))

        return images

    except Exception as e:
        print(f"[!] Failed to list images: {e}")
        return []


def remove_docker_image(image_name: str, force: bool = False) -> bool:
    """
    Remove a Docker image.

    Args:
        image_name: Name of image to remove
        force: If True, force removal even if containers are using it

    Returns:
        True if removal successful, False otherwise
    """
    if not check_docker_available():
        return False

    cmd = ["docker", "rmi"]

    if force:
        cmd.append("-f")

    cmd.append(image_name)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode == 0:
            print(f"[+] Removed image: {image_name}")
            return True
        else:
            print(f"[!] Failed to remove image: {result.stderr}")
            return False

    except Exception as e:
        print(f"[!] Error removing image: {e}")
        return False
