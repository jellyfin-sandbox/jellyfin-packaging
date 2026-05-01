#!/usr/bin/env python3

# build.py - Build packages in a Docker wrapper
#
# Part of the Jellyfin CI system
###############################################################################

from argparse import ArgumentParser
from datetime import datetime
from email.utils import format_datetime, localtime
from git import Repo
from os import getenv
import os.path
from packaging.version import Version
from subprocess import run, PIPE
import sys
from yaml import load, SafeLoader

# Determine top level directory of this repository ("jellyfin-packaging")
revparse = run(["git", "rev-parse", "--show-toplevel"], stdout=PIPE)
repo_root_dir = revparse.stdout.decode().strip()

# Base Docker commands
docker_build_cmd = "docker buildx build --progress=plain --no-cache"
docker_run_cmd = "docker run --rm"


def log(message):
    print(message, flush=True)


# Configuration loader
try:
    with open("build.yaml", encoding="utf-8") as fh:
        configurations = load(fh, Loader=SafeLoader)
except Exception as e:
    log(f"Error: Failed to find 'build.yaml' configuration: {e}")
    exit(1)


# Shared functions
def _determine_arch(build_type, build_arch, build_version):
    PACKAGE_ARCH = (
        configurations[build_type]["archmaps"][build_arch]["PACKAGE_ARCH"]
        if build_arch in configurations[build_type]["archmaps"].keys()
        else None
    )
    if PACKAGE_ARCH is None:
        raise ValueError(
            f"{build_arch} is not a valid {build_type} {build_version} architecture in {configurations[build_type]['archmaps'].keys()}"
        )
    else:
        return PACKAGE_ARCH

def _determine_framework_versions():
    # Prepare repo object for this repository
    this_repo = Repo(repo_root_dir)

    framework_args = dict()

    for submodule in this_repo.submodules:
        if submodule.name in configurations["frameworks"].keys():
            for framework_arg in configurations["frameworks"][submodule.name].keys():
                framework_args[framework_arg] = None
                def sort_versions(input_dict):
                    return dict(sorted(input_dict.items(), key=lambda item: Version(str(item[1]))))
                for commit_hash in sort_versions(configurations["frameworks"][submodule.name][framework_arg]):
                    try:
                        commit = submodule.module().commit(commit_hash)
                        if commit in submodule.module().iter_commits('HEAD'):
                            framework_args[framework_arg] = configurations["frameworks"][submodule.name][framework_arg][commit_hash]
                    except ValueError:
                        continue

    log(f"Determined the following framework versions based on current HEAD values:")
    for k, v in framework_args.items():
        log(f"  * {k}: {v}")
    log("")

    return framework_args


def build_package_deb(
    jellyfin_version, build_type, build_arch, build_version, local=False, debug=False
):
    """
    Build a .deb package (Debian or Ubuntu) within a Docker container that matches the requested distribution version
    """
    log(f"> Building an {build_arch} {build_type} .deb package...")
    log("")

    try:
        os_type = build_type if build_type in configurations.keys() else None
        if os_type is None:
            raise ValueError(
                f"{build_type} is not a valid OS type in {configurations.keys()}"
            )
        os_version = (
            configurations[build_type]["releases"][build_version]
            if build_version in configurations[build_type]["releases"].keys()
            else None
        )
        if os_version is None:
            raise ValueError(
                f"{build_version} is not a valid {build_type} version in {configurations[build_type]['releases'].keys()}"
            )
        PACKAGE_ARCH = _determine_arch(build_type, build_arch, build_version)
        GCC_ARCH = configurations[build_type]["archmaps"][build_arch]["GCC_ARCH"]
    except Exception as e:
        log(f"Invalid/unsupported arguments: {e}")
        exit(1)

    # Set the dockerfile
    dockerfile = configurations[build_type]["dockerfile"]

    # Set the cross-gcc version
    crossgccvers = configurations[build_type]["cross-gcc"][build_version]

    # Prepare the debian changelog file
    changelog_src = f"{repo_root_dir}/debian/changelog.in"
    changelog_dst = f"{repo_root_dir}/debian/changelog"

    with open(changelog_src) as fh:
        changelog = fh.read()

    if "v" in jellyfin_version:
        comment = f"Jellyfin release {jellyfin_version}, see https://github.com/jellyfin/jellyfin/releases/{jellyfin_version} for details."
    else:
        comment = f"Jellyin unstable release {jellyfin_version}."
    jellyfin_version = jellyfin_version.replace("v", "")

    changelog = changelog.format(
        package_version=jellyfin_version,
        package_build=f"{build_type[:3]}{os_version.replace('.', '')}",
        release_comment=comment,
        release_date=format_datetime(localtime()),
    )

    with open(changelog_dst, "w") as fh:
        fh.write(changelog)

    # Use a unique docker image name for consistency
    imagename = f"{configurations[build_type]['imagename']}-{jellyfin_version}_{build_arch}-{build_type}-{build_version}"

    # Prepare the list of build-args
    build_args = list()
    build_args.append(f"--build-arg PACKAGE_TYPE={os_type}")
    build_args.append(f"--build-arg PACKAGE_VERSION={os_version}")
    build_args.append(f"--build-arg PACKAGE_ARCH={PACKAGE_ARCH}")
    build_args.append(f"--build-arg GCC_ARCH={GCC_ARCH}")
    build_args.append(f"--build-arg GCC_VERSION={crossgccvers}")

    # Determine framework versions
    framework_versions = _determine_framework_versions()
    for arg in framework_versions.keys():
        if framework_versions[arg] is not None:
            build_args.append(
                f"--build-arg {arg}={framework_versions[arg]}"
            )

    build_args = ' '.join(build_args)

    # Build the dockerfile and packages
    log(
        f">>> {docker_build_cmd} {build_args} --file {repo_root_dir}/{dockerfile} --tag {imagename} {repo_root_dir}"
    )
    os.system(
        f"{docker_build_cmd} {build_args} --file {repo_root_dir}/{dockerfile} --tag {imagename} {repo_root_dir}"
    )

    log(
        f">>> {docker_run_cmd} --volume {repo_root_dir}:/jellyfin --volume {repo_root_dir}/out/{build_type}:/dist --env JELLYFIN_VERSION={jellyfin_version} --env CONFIG={'Debug' if debug else 'Release'} --name {imagename} {imagename}"
    )
    os.system(
        f"{docker_run_cmd} --volume {repo_root_dir}:/jellyfin --volume {repo_root_dir}/out/{build_type}:/dist --env JELLYFIN_VERSION={jellyfin_version} --env CONFIG={'Debug' if debug else 'Release'} --name {imagename} {imagename}"
    )


def build_linux(
    jellyfin_version, build_type, build_arch, _build_version, local=False, debug=False
):
    """
    Build a portable Linux archive
    """
    log(f"> Building a portable {build_arch} Linux archive...")
    log("")

    try:
        PACKAGE_ARCH = _determine_arch(build_type, build_arch, _build_version)
        DOTNET_ARCH = configurations[build_type]["archmaps"][build_arch]["DOTNET_ARCH"]
    except Exception as e:
        log(f"Invalid/unsupported arguments: {e}")
        exit(1)

    jellyfin_version = jellyfin_version.replace("v", "")

    # Set the dockerfile
    dockerfile = configurations[build_type]["dockerfile"]

    # Use a unique docker image name for consistency
    imagename = f"{configurations[build_type]['imagename']}-{jellyfin_version}_{build_arch}-{build_type}"

    # Set the archive type (tar-gz or zip)
    archivetypes = f"{configurations[build_type]['archivetypes']}"

    # Prepare the list of build-args
    build_args = list()

    # Determine framework versions
    framework_versions = _determine_framework_versions()
    for arg in framework_versions.keys():
        if framework_versions[arg] is not None:
            build_args.append(
                f"--build-arg {arg}={framework_versions[arg]}"
            )

    build_args = ' '.join(build_args)

    # Build the dockerfile and packages
    log(
        f">>> {docker_build_cmd} {build_args} --file {repo_root_dir}/{dockerfile} --tag {imagename} {repo_root_dir}"
    )
    os.system(
        f"{docker_build_cmd} {build_args} --file {repo_root_dir}/{dockerfile} --tag {imagename} {repo_root_dir}"
    )

    log(
        f">>> {docker_run_cmd} --volume {repo_root_dir}:/jellyfin --volume {repo_root_dir}/out/{build_type}:/dist --env JELLYFIN_VERSION={jellyfin_version} --env BUILD_TYPE={build_type} --env PACKAGE_ARCH={PACKAGE_ARCH} --env DOTNET_TYPE=linux --env DOTNET_ARCH={DOTNET_ARCH} --env ARCHIVE_TYPES={archivetypes} --env CONFIG={'Debug' if debug else 'Release'} --name {imagename} {imagename}"
    )
    os.system(
        f"{docker_run_cmd} --volume {repo_root_dir}:/jellyfin --volume {repo_root_dir}/out/{build_type}:/dist --env JELLYFIN_VERSION={jellyfin_version} --env BUILD_TYPE={build_type} --env PACKAGE_ARCH={PACKAGE_ARCH} --env DOTNET_TYPE=linux --env DOTNET_ARCH={DOTNET_ARCH} --env ARCHIVE_TYPES={archivetypes} --env CONFIG={'Debug' if debug else 'Release'} --name {imagename} {imagename}"
    )


def build_windows(
    jellyfin_version, build_type, _build_arch, _build_version, local=False, debug=False
):
    """
    Build a portable Windows archive
    """
    log(f"> Building a portable {build_arch} Windows archive...")
    log("")

    try:
        PACKAGE_ARCH = _determine_arch(build_type, build_arch, _build_version)
        DOTNET_ARCH = configurations[build_type]["archmaps"][build_arch]["DOTNET_ARCH"]
    except Exception as e:
        log(f"Invalid/unsupported arguments: {e}")
        exit(1)

    jellyfin_version = jellyfin_version.replace("v", "")

    # Set the dockerfile
    dockerfile = configurations[build_type]["dockerfile"]

    # Use a unique docker image name for consistency
    imagename = f"{configurations[build_type]['imagename']}-{jellyfin_version}_{build_arch}-{build_type}"

    # Set the archive type (tar-gz or zip)
    archivetypes = f"{configurations[build_type]['archivetypes']}"

    # Prepare the list of build-args
    build_args = list()

    # Determine framework versions
    framework_versions = _determine_framework_versions()
    for arg in framework_versions.keys():
        if framework_versions[arg] is not None:
            build_args.append(
                f"--build-arg {arg}={framework_versions[arg]}"
            )

    build_args = ' '.join(build_args)

    # Build the dockerfile and packages
    log(
        f">>> {docker_build_cmd} {build_args} --file {repo_root_dir}/{dockerfile} --tag {imagename} {repo_root_dir}"
    )
    os.system(
        f"{docker_build_cmd} {build_args} --file {repo_root_dir}/{dockerfile} --tag {imagename} {repo_root_dir}"
    )

    log(
        f">>> {docker_run_cmd} --volume {repo_root_dir}:/jellyfin --volume {repo_root_dir}/out/{build_type}:/dist --env JELLYFIN_VERSION={jellyfin_version} --env BUILD_TYPE={build_type} --env PACKAGE_ARCH={PACKAGE_ARCH} --env DOTNET_TYPE=win --env DOTNET_ARCH={DOTNET_ARCH} --env ARCHIVE_TYPES={archivetypes} --env CONFIG={'Debug' if debug else 'Release'} --name {imagename} {imagename}"
    )
    os.system(
        f"{docker_run_cmd} --volume {repo_root_dir}:/jellyfin --volume {repo_root_dir}/out/{build_type}:/dist --env JELLYFIN_VERSION={jellyfin_version} --env BUILD_TYPE={build_type} --env PACKAGE_ARCH={PACKAGE_ARCH} --env DOTNET_TYPE=win --env DOTNET_ARCH={DOTNET_ARCH} --env ARCHIVE_TYPES={archivetypes} --env CONFIG={'Debug' if debug else 'Release'} --name {imagename} {imagename}"
    )


def build_macos(
    jellyfin_version, build_type, build_arch, _build_version, local=False, debug=False
):
    """
    Build a portable MacOS archive
    """
    log(f"> Building a portable {build_arch} MacOS archive...")
    log("")

    try:
        PACKAGE_ARCH = _determine_arch(build_type, build_arch, _build_version)
        DOTNET_ARCH = configurations[build_type]["archmaps"][build_arch]["DOTNET_ARCH"]
    except Exception as e:
        log(f"Invalid/unsupported arguments: {e}")
        exit(1)

    jellyfin_version = jellyfin_version.replace("v", "")

    # Set the dockerfile
    dockerfile = configurations[build_type]["dockerfile"]

    # Use a unique docker image name for consistency
    imagename = f"{configurations[build_type]['imagename']}-{jellyfin_version}_{build_arch}-{build_type}"

    # Set the archive type (tar-gz or zip)
    archivetypes = f"{configurations[build_type]['archivetypes']}"

    # Prepare the list of build-args
    build_args = list()

    # Determine framework versions
    framework_versions = _determine_framework_versions()
    for arg in framework_versions.keys():
        if framework_versions[arg] is not None:
            build_args.append(
                f"--build-arg {arg}={framework_versions[arg]}"
            )

    build_args = ' '.join(build_args)

    # Build the dockerfile and packages
    log(
        f">>> {docker_build_cmd} {build_args} --file {repo_root_dir}/{dockerfile} --tag {imagename} {repo_root_dir}"
    )
    os.system(
        f"{docker_build_cmd} {build_args} --file {repo_root_dir}/{dockerfile} --tag {imagename} {repo_root_dir}"
    )

    log(
        f">>> {docker_run_cmd} --volume {repo_root_dir}:/jellyfin --volume {repo_root_dir}/out/{build_type}:/dist --env JELLYFIN_VERSION={jellyfin_version} --env BUILD_TYPE={build_type} --env PACKAGE_ARCH={PACKAGE_ARCH} --env DOTNET_TYPE=osx --env DOTNET_ARCH={DOTNET_ARCH} --env ARCHIVE_TYPES={archivetypes} --env CONFIG={'Debug' if debug else 'Release'} --name {imagename} {imagename}"
    )
    os.system(
        f"{docker_run_cmd} --volume {repo_root_dir}:/jellyfin --volume {repo_root_dir}/out/{build_type}:/dist --env JELLYFIN_VERSION={jellyfin_version} --env BUILD_TYPE={build_type} --env PACKAGE_ARCH={PACKAGE_ARCH} --env DOTNET_TYPE=osx --env DOTNET_ARCH={DOTNET_ARCH} --env ARCHIVE_TYPES={archivetypes} --env CONFIG={'Debug' if debug else 'Release'} --name {imagename} {imagename}"
    )


def build_portable(
    jellyfin_version, build_type, _build_arch, _build_version, local=False, debug=False
):
    """
    Build a portable .NET archive
    """
    log("> Building a portable .NET archive...")
    log("")

    jellyfin_version = jellyfin_version.replace("v", "")

    # Set the dockerfile
    dockerfile = configurations[build_type]["dockerfile"]

    # Use a unique docker image name for consistency
    imagename = (
        f"{configurations[build_type]['imagename']}-{jellyfin_version}_{build_type}"
    )

    # Set the archive type (tar-gz or zip)
    archivetypes = f"{configurations[build_type]['archivetypes']}"

    # Prepare the list of build-args
    build_args = list()

    # Determine framework versions
    framework_versions = _determine_framework_versions()
    for arg in framework_versions.keys():
        if framework_versions[arg] is not None:
            build_args.append(
                f"--build-arg {arg}={framework_versions[arg]}"
            )

    build_args = ' '.join(build_args)

    # Build the dockerfile and packages
    log(
        f">>> {docker_build_cmd} {build_args} --file {repo_root_dir}/{dockerfile} --tag {imagename} {repo_root_dir}"
    )
    os.system(
        f"{docker_build_cmd} {build_args} --file {repo_root_dir}/{dockerfile} --tag {imagename} {repo_root_dir}"
    )

    log(
        f">>> {docker_run_cmd} --volume {repo_root_dir}:/jellyfin --volume {repo_root_dir}/out/{build_type}:/dist --env JELLYFIN_VERSION={jellyfin_version} --env BUILD_TYPE={build_type} --env ARCHIVE_TYPES={archivetypes} --env CONFIG={'Debug' if debug else 'Release'} --name {imagename} {imagename}"
    )
    os.system(
        f"{docker_run_cmd} --volume {repo_root_dir}:/jellyfin --volume {repo_root_dir}/out/{build_type}:/dist --env JELLYFIN_VERSION={jellyfin_version} --env BUILD_TYPE={build_type} --env ARCHIVE_TYPES={archivetypes} --env CONFIG={'Debug' if debug else 'Release'} --name {imagename} {imagename}"
    )


def build_docker(
    jellyfin_version, build_type, build_arch, _build_version, local=False, debug=False
):
    """
    Build a Docker image for a single architecture and load it into the local daemon
    """
    log(f"> Building Docker image for {build_arch}...")
    log("")

    # Set the dockerfile
    dockerfile = configurations[build_type]["dockerfile"]

    jellyfin_version = jellyfin_version.replace("v", "")

    log(f"NOTE: Building version {jellyfin_version} for {build_arch}")
    log("")

    # Get our ARCH variables from the archmaps
    PACKAGE_ARCH = configurations["docker"]["archmaps"][build_arch]["PACKAGE_ARCH"]
    DOTNET_ARCH = configurations["docker"]["archmaps"][build_arch]["DOTNET_ARCH"]
    IMAGE_ARCH = configurations["docker"]["archmaps"][build_arch]["IMAGE_ARCH"]
    TARGET_ARCH = configurations["docker"]["archmaps"][build_arch]["TARGET_ARCH"]

    # Use a consistent per-arch image name (no date suffix; overwritten on rebuild)
    imagename = f"{configurations['docker']['imagename']}:{jellyfin_version}-{build_arch}"

    # Clean up any existing qemu static image
    log(f">>> {docker_run_cmd} --privileged linuxserver/qemu-static --reset -p yes")
    os.system(f"{docker_run_cmd} --privileged linuxserver/qemu-static --reset -p yes")
    log("")

    # Prepare the list of build-args
    build_args = list()
    build_args.append(f"--build-arg PACKAGE_ARCH={PACKAGE_ARCH}")
    build_args.append(f"--build-arg DOTNET_ARCH={DOTNET_ARCH}")
    build_args.append(f"--build-arg IMAGE_ARCH={IMAGE_ARCH}")
    build_args.append(f"--build-arg TARGET_ARCH={TARGET_ARCH}")
    build_args.append(f"--build-arg JELLYFIN_VERSION={jellyfin_version}")
    build_args.append(f"--build-arg CONFIG={'Debug' if debug else 'Release'}")
    build_args.append("--load")

    # Determine framework versions
    framework_versions = _determine_framework_versions()
    for arg in framework_versions.keys():
        if framework_versions[arg] is not None:
            build_args.append(f"--build-arg {arg}={framework_versions[arg]}")

    build_args = ' '.join(build_args)

    # Build the dockerfile
    log(f">>> {docker_build_cmd} {build_args} --file {repo_root_dir}/{dockerfile} --tag {imagename} {repo_root_dir}")
    ret = os.system(f"{docker_build_cmd} {build_args} --file {repo_root_dir}/{dockerfile} --tag {imagename} {repo_root_dir}")
    if ret > 0:
        exit(1)


def build_nuget(
    jellyfin_version, build_type, _build_arch, _build_version, local=False, debug=False
):
    """
    Pack and upload nuget packages
    """
    log("> Building Nuget packages...")
    log("")

    project_files = configurations["nuget"]["projects"]
    log(project_files)

    # Determine if this is a "latest"-type image (v in jellyfin_version) or not
    if "v" in jellyfin_version and not "rc" in jellyfin_version:
        is_stable = True
        is_preview = False
    elif "rc" in jellyfin_version:
        is_stable = False
        is_preview = True
    else:
        is_stable = False
        is_preview = False

    jellyfin_version = jellyfin_version.replace("v", "")

    # Set today's date in a convenient format for use as an image suffix
    date = datetime.now().strftime("%Y%m%d%H%M%S")

    pack_command_base = "dotnet pack -o out/nuget/"
    if is_stable or is_preview:
        pack_command = f"{pack_command_base} -p:Version={jellyfin_version}"
    else:
        pack_command = (
            f"{pack_command_base} --version-suffix {date} -p:Stability=Unstable"
        )

    for project in project_files:
        log(f">> Packing  {project}...")
        log("")

        project_pack_command = f"{pack_command} jellyfin-server/{project}"
        log(f">>>> {project_pack_command}")
        os.system(project_pack_command)

    if local:
        return

    if is_stable or is_preview:
        nuget_repo = configurations["nuget"]["feed_urls"]["stable"]
        nuget_key = getenv("NUGET_STABLE_KEY")
    else:
        nuget_repo = configurations["nuget"]["feed_urls"]["unstable"]
        nuget_key = getenv("NUGET_UNSTABLE_KEY")

    if nuget_key is None:
        log(f"Error: Failed to get NUGET_*_KEY environment variable")
        exit(1)

    push_command = f"dotnet nuget push out/nuget/*.nupkg -s {nuget_repo} -k {nuget_key}"
    log(f">>>> {push_command}")
    os.system(push_command)


def usage():
    """
    Print usage information on error
    """
    log(f"{sys.argv[0]} JELLYFIN_VERSION BUILD_TYPE [BUILD_ARCH] [BUILD_VERSION]")
    log("  JELLYFIN_VERSION: The Jellyfin version being built")
    log("    * Stable releases should be tag names with a 'v' e.g. v10.9.0")
    log(
        "    * Unstable releases should be 'master' or a date-to-the-hour version e.g. 2024021600"
    )
    log("  BUILD_TYPE: The type of build to execute")
    log(f"    * Valid options are: {', '.join(configurations.keys())}")
    log("  BUILD_ARCH: The CPU architecture of the build")
    log("    * Valid options are: <empty> [portable only], amd64, arm64")
    log("  BUILD_VERSION: A valid OS distribution version (.deb build types only)")


# Define a map of possible build functions from the YAML configuration
function_definitions = {
    "build_package_deb": build_package_deb,
    "build_portable": build_portable,
    "build_linux": build_linux,
    "build_windows": build_windows,
    "build_macos": build_macos,
    "build_portable": build_portable,
    "build_docker": build_docker,
    "build_nuget": build_nuget,
}


parser = ArgumentParser(
    prog='build.py',
    description='Jellyfin build automator',
    epilog='See "README.md" and "build.yaml" for the full details of what this tool can build at this time.',
)

parser.add_argument('jellyfin_version', help='The output version')
parser.add_argument('build_type', choices=configurations.keys(), help='The build platform')
parser.add_argument('build_arch', default=None, nargs='?', help='The build architecture')
parser.add_argument('build_version', default=None, nargs='?', help='The build release version [debian/ubuntu only]')
parser.add_argument('--local', action='store_true', help='Local build, do not push packages [nuget only]')
parser.add_argument('--debug', action='store_true', help='Debug build, set .NET to use Debug instead of Release')

args = parser.parse_args()

jellyfin_version = args.jellyfin_version
build_type = args.build_type
build_arch = args.build_arch
build_version = args.build_version

if build_type not in ["portable", "nuget"] and not build_arch:
    log(f"Error: You must specify an architecture for build platform {build_type}")
    exit(1)

# Autocorrect "master" to a dated version string
if jellyfin_version in ["auto", "master"]:
    jellyfin_version = datetime.now().strftime("%Y%m%d%H")
    log(f"NOTE: Autocorrecting 'master' version to {jellyfin_version}")

# Launch the builder function
function_definitions[configurations[build_type]["build_function"]](
    jellyfin_version, build_type, build_arch, build_version, local=args.local, debug=args.debug
)
