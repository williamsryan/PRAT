#!/usr/bin/env python3

import argparse
import subprocess
import sys, os
import shutil
import tempfile

import toml
from buildparser.buildparser import cmake_parser
from buildparser.buildparser import auto_parser

def makeDiffs(path1, path2, feat):
    print("[+] Checking for matching files in {} and {}"
        .format(path1,  path2))
    
    unused_files = []
    
    aFiles = {os.path.splitext(x)[0] for x in os.listdir(path1)}
    bFiles = {os.path.splitext(x)[0] for x in os.listdir(path2)}

    outdir = "diff_" + feat
    p = subprocess.Popen(["mkdir", "-p", outdir])
    p.wait()
    p = subprocess.Popen(["mkdir", "-p", "reports"])
    p.wait()

    for f in aFiles:
        # We only diff files that exist in both compilations.
        if f in bFiles:
            #print("[+] {}".format(f))
            # Make diffs of the file and save in another folder.
            target = f + ".gcov"
            abs_target = outdir + "/" + target
            out = open(abs_target, 'w')
            p = subprocess.Popen(["diff", "-u", path1 + "/" + target, path2 + "/" + target], stdout=out)
            p.wait()
        else:
            # If an entire file is left out, we could posit that
            # it is only used when the tested feature ie enabled.
            print("[+] {} only exists with {} enabled".format(f, feat))
            # These files are useful in some cases. Save and mark for deletion later.
            unused_files.append(f)
    
    # Clean up empty files.
    for covFile in os.listdir(outdir):
        real_file = outdir + "/" + covFile
        if not os.path.getsize(real_file):
            #print("[-] {} is empty. Deleting".format(covFile))
            os.remove(real_file)
        else:
            # Now that we've cleaned up.
            # Generate HTML files here.
            if isTool("pygmentize"):
                print("[+] Generating HTML assets...")
                # Generate individual, stylized HTML files.
                p = subprocess.Popen(["pygmentize", "-l", "diff", "-f", "html", "-O", "full", "-o", "reports/" + covFile + "-diff.html", real_file])
                p.wait()
            else:
                print("[-] `pygments` is not available. Install with: `pip install Pygments`")
                continue
    
    #return unused_files
    return outdir

def extractFeatures(path):
    print("[+] Extract features for removal from: {}".format(path))
    p = subprocess.Popen(["perl", "extract_features.pl", path + "/"])
    p.wait()
    print("[+] in extractFeatures function, has finished perl script.")

    # if isTool("xdot"):
    #     p = subprocess.Popen(["xdot", "FDG.dot"])
    #     p.wait()
    # else:
    #     print("[-] `xdot` is not available. Saving to FDG.dot")
    
    # TODO: make this output content from `genhtml` or something to
    # make the output a hierarchical webpage showing source files
    # and not just the current graphviz output.
    html = """
    <!DOCTYPE html>
    <head>
        <title>Debloating Report</title>
        <meta charset="utf-8">

        <link rel="stylesheet" href="styles/styles.css"/>
        <link rel="stylesheet" type="text/css" href="https://cdn.jsdelivr.net/npm/diff2html/bundles/css/diff2html.min.css" />
        <link rel="stylesheet" href="https://maxcdn.bootstrapcdn.com/bootstrap/4.0.0/css/bootstrap.min.css" integrity="sha384-Gn5384xqQ1aoWXA+058RXPxPg6fy4IWvTNh0E263XmFcJlSAwiGgFAW/dAiS6JXm" crossorigin="anonymous">

        <script src="https://code.jquery.com/jquery-3.2.1.slim.min.js" integrity="sha384-KJ3o2DKtIkvYIK3UENzmM7KCkRr/rE9/Qpg6aAZGJwFDMVNA/GpGFF93hXpG5KkN" crossorigin="anonymous"></script>
        <script src="https://cdnjs.cloudflare.com/ajax/libs/popper.js/1.12.9/umd/popper.min.js" integrity="sha384-ApNbgh9B+Y1QKtv3Rn7W3mgPxhU9K/ScQsAP7hUibX39j7fakFPskvXusvfa0b4Q" crossorigin="anonymous"></script>
        <script src="https://maxcdn.bootstrapcdn.com/bootstrap/4.0.0/js/bootstrap.min.js" integrity="sha384-JZR6Spejh4U02d8jOt6vLEHfe/JQGiRRSQQxSfFWpi1MquVdAyjUar5+76PVCmYl" crossorigin="anonymous"></script>

        <script src="https://code.jquery.com/jquery-3.3.1.min.js"></script>
        <script src="js/main.js"></script>
    </head>
        <body>
        <h3>Code to Remove for Feature: %s</h3>
        <table class="table table-striped" id="scTab">
            <thead>
            <tr>
                <th scope="col">Source File</th>
                <th scope="col">LoC to Remove</th>
            </tr>
            </thead>
            <tbody id="scBody">
    """ % feature

    # Total LoC count.
    tot_count = 0

    for report in os.listdir("./reports"):

        # Count LoC to remove per file.
        report_fh = open("./reports/" + report, 'r')
        count = 0
        for line in report_fh.readlines():
            if "####" in line:
                count += 1
        tot_count += count
        html += "<tr><td>"
        html += "<a href=\"./reports/%s\" target=\"_blank\">%s</a><br/>" % (report, report)
        html += "</td><td>%d" % count
        html += "</td></tr>"
        report_fh.close()
    
    html += "<tr><td><b>Total LoC to Remove</b></td><td><b>%d</b></td></tr>" % tot_count
    html += "</tbody></table></body></html>"

    outhtml = open("report.html", 'w')
    outhtml.write(html)
    outhtml.close()

def deleteFeatures(path):
    print("[+] Extract features for removal from: {}".format(path))
    p = subprocess.Popen(["perl", "extract_features.pl", path + "/", "--delete"])
    p.wait()
    print("[+] in deleteFeatures function, has finished perl script.")

# Generate coverage files for Mosquitto.
def makeMosquitto(path, feature, flag, tests=False):
    print("[+] Running in: {}".format(path))
    target = "WITH_" + feature + "=" + flag
    p = subprocess.Popen(["make", "clean"], cwd=path)
    p.wait()
    p = subprocess.Popen(["make", "binary", "-j", "WITH_COVERAGE=yes", target], cwd=path)
    p.wait()

    # Add part here later for running tests.
    if tests is not False:
        p = subprocess.Popen(["make", "utest", "-j", "WITH_COVERAGE=yes"], cwd=path)
        p.wait()
    else:
        print("[+] Not running tests. Continuing.")

    # Generate gcov files.
    src = path + "/src"
    lib = path + "/lib"
    print("[+] Running in: {} and {}".format(src, lib))
    p = subprocess.Popen("llvm-cov-9 gcov *", shell=True, cwd=src)
    p.wait()
    p = subprocess.Popen("llvm-cov-9 gcov *", shell=True, cwd=lib)
    p.wait()

    # Make directories for storing the results.
    coverageFiles = "coverage_files_WITH_" + feature + "_" + flag
    p = subprocess.Popen("mkdir -p " + coverageFiles, shell=True, cwd=path)
    p.wait()
    # p = subprocess.Popen("mv " + src + "/*.gcov " + coverageFiles, shell=True, cwd=path)
    p = subprocess.Popen("mv src/*.gcov " + coverageFiles, shell=True, cwd=path)
    p.wait()
    p = subprocess.Popen("mv lib/*.gcov " + coverageFiles, shell=True, cwd=path)
    p.wait()

    # Move the files to working dir.
    home = os.getcwd()
    p = subprocess.Popen(["mv", coverageFiles, home], cwd=path)
    p.wait()

def makeMosquitto2(path, feature, flag):
    print("[+] Running in: {}".format(path))
    target = "WITH_" + feature + "=" + flag
    p = subprocess.Popen(["make", "clean"], cwd=path)
    p.wait()
    p = subprocess.Popen(["make", "binary", "-j", "WITH_COVERAGE=yes", target], cwd=path)
    p.wait()

    # os.system("cd /home/klee/PRAT/artifacts/mosquitto/ && make binary -j")
    os.system("klee -emit-all-errors -only-output-states-covering-new -link-llvm-lib=/home/klee/PRAT/artifacts/mosquitto/lib/libmosquitto.so.1 -link-llvm-lib=/home/klee/PRAT/artifacts/mosquitto/src/net.bc -link-llvm-lib=/home/klee/PRAT/artifacts/mosquitto/src/sys_tree.bc --libc=uclibc --posix-runtime --solver-backend=z3 /home/klee/PRAT/artifacts/mosquitto/src/mosquitto.bc --sym-args 0 3 4 --sym-files 2 4 --max-fail 1 --max-time=60")
    os.system("cd /home/klee/PRAT/src/")

    # Generate gcov files.
    src = path + "/src"
    lib = path + "/lib"
    print("[+] Running in: {} and {}".format(src, lib))
    p = subprocess.Popen("llvm-cov-9 gcov *", shell=True, cwd=src)
    p.wait()
    p = subprocess.Popen("llvm-cov-9 gcov *", shell=True, cwd=lib)
    p.wait()

    # Make directories for storing the results.
    coverageFiles = "coverage_files_WITH_" + feature + "_" + flag
    p = subprocess.Popen("mkdir -p " + coverageFiles, shell=True, cwd=path)
    p.wait()
    # p = subprocess.Popen("mv " + src + "/*.gcov " + coverageFiles, shell=True, cwd=path)
    p = subprocess.Popen("mv src/*.gcov " + coverageFiles, shell=True, cwd=path)
    p.wait()
    p = subprocess.Popen("mv lib/*.gcov " + coverageFiles, shell=True, cwd=path)
    p.wait()

    # Move the files to working dir.
    home = os.getcwd()
    p = subprocess.Popen(["mv", coverageFiles, home], cwd=path)
    p.wait()

def makeFFmpeg(path, feature, flag, tests=False):
    print("[+] Running in: {}".format(path))

    # This is just a test for now, but could be useful later.
    # TODO: make a baseline/non-feature specific test.
    if feature == "baseline":
        if flag == "yes":
            # No explicit 'enable' flag for FFmpeg.
            p = subprocess.Popen(["bash", "configure", "--toolchain=gcov"], cwd=path)
            p.wait()
        else:
            target = "--disable-" + feature
            p = subprocess.Popen(["bash", "configure", "--toolchain=gcov", target], cwd=path)
            #p = subprocess.Popen("bash configure --toolchain=gcov --disable-", shell=True, cwd=path)
            p.wait()
    else:
        # Prep the build system using configure.
        if flag == "yes":
            # No explicit 'enable' flag for FFmpeg.
            p = subprocess.Popen(["bash", "configure", "--toolchain=gcov"], cwd=path)
            p.wait()
        else:
            target = "--disable-" + feature
            p = subprocess.Popen(["bash", "configure", "--toolchain=gcov", target], cwd=path)
            #p = subprocess.Popen("bash configure --toolchain=gcov --disable-", shell=True, cwd=path)
            p.wait()
    
    p = subprocess.Popen(["make", "clean"], cwd=path)
    p.wait()

    p = subprocess.Popen(["make", "-j3"], cwd=path)
    p.wait()

    # Add part later for running tests.
    if tests is not False:
        p = subprocess.Popen(["make", "fate", "-j3", "SAMPLES=fate-suite/"], cwd=path)
        p.wait()

    #p = subprocess.Popen(["./ffmpeg", "--help"], cwd=path)
    #p.wait()

    # FFmpeg requires this version, not llvm-cov.
    p = subprocess.Popen("gcov libavcodec/*", shell=True, cwd=path)
    p.wait()
    p = subprocess.Popen("gcov libavfilter/*", shell=True, cwd=path)
    p.wait()
    p = subprocess.Popen("gcov libavformat/*", shell=True, cwd=path)
    p.wait()

    # Make directories for storing the results.
    coverageFiles = "coverage_files_WITH_" + feature + "_" + flag
    print(f"[+] in makeFFmpeg function: {coverageFiles}")
    p = subprocess.Popen("mkdir -p " + coverageFiles, shell=True, cwd=path)
    p.wait()
    p = subprocess.Popen("mv " + "*.gcov " + coverageFiles, shell=True, cwd=path)
    p.wait()
    p = subprocess.Popen("mv " + "*.gcov " + coverageFiles, shell=True, cwd=path)
    p.wait()
    p = subprocess.Popen("mv " + "*.gcov " + coverageFiles, shell=True, cwd=path)
    p.wait()

    # Move the files to working dir.
    home = os.getcwd()
    p = subprocess.Popen(["mv", coverageFiles, home], cwd=path)
    p.wait()

def makeRust(path, feature, flag, tests=False):
    print("[+] Prepping Rust environment for instrumentation...")
    os.environ["CARGO_INCREMENTAL"] = "0"
    os.environ["RUSTFLAGS"] = "-Zprofile -Ccodegen-units=1 -Copt-level=0 -Clink-dead-code -Coverflow-checks=off -Zpanic_abort_tests -Cpanic=abort"
    os.environ["RUSTDOCFLAGS"] = "-Cpanic=abort"

    # rustup install nightly
    # rustup default nightly

    print("[+] Loading `Cargo.toml`...")
    cargo = toml.load(path + "/Cargo.toml")
    features = cargo["features"]

    print("[+] Found {} features\n".format(len(features)))

    p = subprocess.Popen(["cargo", "clean"], cwd=path)
    p.wait()

    #for f in features:
    #    print("[+] {}".format(f))
    
    if flag == "yes":
        p = subprocess.Popen(["cargo", "build", "--features", feature], cwd=path)
        p.wait()
    else:
        p = subprocess.Popen(["cargo", "build", "--no-default-features"], cwd=path)
        p.wait()
    
    if tests is not False:
        # Now generate the coverage files using kcov.
        p = subprocess.Popen(["cargo", "test"], cwd=path)
        p.wait()

    src = path + "/target/debug/deps/"
    p = subprocess.Popen("gcov-9 *", shell=True, cwd=src)
    p.wait()

    # Make directories for storing the results.
    coverageFiles = "coverage_files_WITH_" + feature + "_" + flag
    p = subprocess.Popen("mkdir -p " + coverageFiles, shell=True, cwd=path)
    p.wait()
    p = subprocess.Popen("mv " + src + "*.gcov " + coverageFiles, shell=True, cwd=path)
    p.wait()

    # Move the files to working dir.
    home = os.getcwd()
    p = subprocess.Popen(["mv", coverageFiles, home], cwd=path)
    p.wait()

def featureDiscovery_Rust(path):
    # print("[+] Prepping Rust environment for instrumentation...")
    # os.environ["CARGO_INCREMENTAL"] = "0"
    # os.environ["RUSTFLAGS"] = "-Zprofile -Ccodegen-units=1 -Copt-level=0 -Clink-dead-code -Coverflow-checks=off -Zpanic_abort_tests -Cpanic=abort"
    # os.environ["RUSTDOCFLAGS"] = "-Cpanic=abort"

    # rustup install nightly
    # rustup default nightly

    print("[+] Loading 'Cargo.toml'...")
    cargo = toml.load(path + "/Cargo.toml")
    features = cargo["features"]

    print("[+] Found {} features\n".format(len(features)))

    print("[+] All features are:")

    for f in features:
       print("[%] {}".format(f))

def featureDiscovery_cMake(path):
    print("[+] Loading 'CMakeLists.txt'...")
    with tempfile.TemporaryDirectory() as tempdir:
        abspath = os.path.abspath(path)
        os.system("cd %s; cmake -LA %s > cmk_out" % (tempdir, abspath))
        features = cmake_parser(os.path.join(tempdir, 'cmk_out'))
    print("[+] Found %d features\n" % len(features))
    print("[+] All features are:")
    for f in features:
       print("[%] {}".format(f))

def featureDiscovery_auto(path):
    print("[+] Loading 'configure'...")
    with tempfile.TemporaryDirectory() as tempdir:
        cfgF = os.path.join(path, "configure")
        tmpF = os.path.join(tempdir, "cfg_out")
        os.system("%s --help > %s" % (cfgF, tmpF))
        features = auto_parser(tmpF)
    print("[+] Found %d features\n" % len(features))
    print("[+] All features are:")
    for f in features:
       print("[%] {}".format(f))

def makeAOM(path, feature, flag, tests=False):
    print("[+] Running in: {}".format(path))

    if flag == "yes":
        target = "-DCONFIG_" + feature + "=1"
    else:
        target = "-DCONFIG_" + feature + "=0"

    build = path + "/build"
    p = subprocess.Popen(["cmake", target, ".."], cwd=build)
    p.wait()

    #p = subprocess.Popen(["make", "clean"], cwd=path)
    #p.wait()
    p = subprocess.Popen(["make", "-j3"], cwd=build)
    p.wait()

    # Add part here later for running tests.
    if tests is not False:
        p = subprocess.Popen("./test_libaom", shell=True, cwd=build)
        p.wait()
    else:
        print("[+] Not running tests. Continuing.")

    # Generate gcov files.
    src = path + "/build/CMakeFiles/aom.dir/aom/src/"
    p = subprocess.Popen("gcov *", shell=True, cwd=src)
    p.wait()

    # Make directories for storing the results.
    coverageFiles = "coverage_files_WITH_" + feature + "_" + flag
    p = subprocess.Popen("mkdir -p " + coverageFiles, shell=True, cwd=path)
    p.wait()
    p = subprocess.Popen("mv " + src + "/*.gcov " + coverageFiles, shell=True, cwd=path)
    p.wait()
    #p = subprocess.Popen("mv " + lib + "/*.gcov " + coverageFiles, shell=True, cwd=path)
    #p.wait()

    # Cleanup before leaving.
    p = subprocess.Popen("rm -rf *", shell=True, cwd=build)
    p.wait()
    p = subprocess.Popen("git checkout .", shell=True, cwd=build)
    p.wait()

    # Move the files to working dir.
    home = os.getcwd()
    p = subprocess.Popen(["mv", coverageFiles, home], cwd=path)
    p.wait()

def makeDDS(path, feature, flag, tests=False):
    print("[+] Running in: {}".format(path))

    # Prep the build system using configure.
    if flag == "yes":
        # No explicit 'enable' flag for FFmpeg.
        p = subprocess.Popen(["bash", "configure", "--no-tests"], cwd=path)
        p.wait()
    else:
        target = "--disable-" + feature
        p = subprocess.Popen(["bash", "configure", "--no-tests", target], cwd=path)
        p.wait()
    
    p = subprocess.Popen(["make", "clean"], cwd=path)
    p.wait()

    p = subprocess.Popen(["make", "-j3"], cwd=path)
    p.wait()

    # TODO: finish running tests and making gcov files.

def makeCM(path, feature, flag, tests=False):
    print("[-] TODO: makeCM.")

def isTool(prog):
    return shutil.which(prog) is not None

if __name__ == '__main__':
    # Setup the command line args for different projects.
    parser = argparse.ArgumentParser()
    parser.add_argument("project", help="Directory to project to target")
    parser.add_argument("feature", help="Feature to identify/remove from project", nargs="*")
    parser.add_argument("--list", help="List the features for the target codebase", action="store_true")
    parser.add_argument("--extract", help="Generate feature graph and show LoC to remove", action="store_true")
    parser.add_argument("--tests", help="Run tests at compile time (necessary for better coverage results)", action="store_true")
    parser.add_argument("--delete", help="Attempt to delete entire feature-specific files after analysis", action="store_true")
    parser.add_argument("--klee", help="Run klee to generate test cases", action="store_true")
    args = parser.parse_args()
    
    if args.klee:
        print("[+] Run KLEE to generate test cases")

        feature = args.feature[0].upper()

        makeMosquitto2(args.project, feature, "yes")
        makeMosquitto2(args.project, feature, "no")

        home2 = os.getcwd()
        diffs = makeDiffs(home2 + "/coverage_files_WITH_" + feature + "_yes",
            home2 + "/coverage_files_WITH_" + feature + "_no", feature)
        
        #print(f"Running make clean in: {args.project}")
        p = subprocess.Popen(["make", "clean"], cwd=args.project)
        p.wait()
        extractFeatures(diffs)
        print("[+] Attempting to open with Firefox...")
        p = subprocess.Popen(["firefox", "./report.html"])
        p.wait()
        sys.exit(0)

    home = os.getcwd()

    # Before checking the main loop below; look for list flag.
    if args.list:
        print("[+] Getting features available from: {}".format(args.project))
        # Attempt to auto-detect project type
        tlfiles = [f for f in os.listdir(args.project) if os.path.isfile(os.path.join(args.project, f))]
        if 'Cargo.toml' in tlfiles:
            #Rust project!
            featureDiscovery_Rust(args.project)
        elif 'CMakeLists.txt' in tlfiles:
            #CMake project!
            featureDiscovery_cMake(args.project)
        elif 'configure' in tlfiles:
            #Autotools project!
            featureDiscovery_auto(args.project)
        else:
            print("[+] Project %s uses an unsupported build system. Unable to discover features :-(", args.project)
        sys.exit(0)

    if "mosquitto" in args.project:
        # Mosquitto uses all-caps names.
        feature = args.feature[0].upper()

        # Compile with feature enabled.
        makeMosquitto(args.project, feature, "yes", args.tests)
        # Compile with feature disabled.
        makeMosquitto(args.project, feature, "no", args.tests)

        # Make one file with the `diff` of coverage info.
        diffs = makeDiffs(home + "/coverage_files_WITH_" + feature + "_yes",
            home + "/coverage_files_WITH_" + feature + "_no", feature)
        
        #print(f"Running make clean in: {args.project}")
        p = subprocess.Popen(["make", "clean"], cwd=args.project)
        p.wait()
        if args.delete is not False:
            print("[+] Attempting to delete source files...")
            deleteFeatures(diffs)
            sys.exit(0)
    elif "FFmpeg" in args.project:
        feature = args.feature[0]

        if args.tests:
            if not os.path.isfile(args.project + "/fate-suite"):
                # Download the test suite/etc for FFmpeg.
                p = subprocess.Popen(["make", "fate-rsync", "SAMPLES=fate-suite/"], cwd=args.project)
                p.wait()
                # Now we can also run the tests in `makeFFmpeg`.

        makeFFmpeg(args.project, feature, "yes", args.tests)
        makeFFmpeg(args.project, feature, "no", args.tests)

        # Make one file with the `diff` of coverage info.
        diffs = makeDiffs(home + "/coverage_files_WITH_" + feature + "_yes",
            home + "/coverage_files_WITH_" + feature + "_no", feature)

        if args.delete is not False:
            print("[+] Attempting to delete source files...")
            deleteFeatures(diffs)
            sys.exit(0)
        
        # Attempt to delete feature-specific source files.
        # I made a change that broke this. Will fix later.
        # if args.delete is not False:
        #     print("[+] Attempting to delete source files...")
        #     # for td in diffs:
        #     for tdp in os.listdir(diffs):
        #         tdt = tdp.split(".")
        #         td = tdt[0]
        #         for i in range(1, len(tdt)-1):
        #             td = td + '.' + tdt[i]
        #         if os.path.exists(args.project + "/libavfilter/" + td):
        #             os.remove(args.project + "/libavfilter/" + td)
        #         elif os.path.exists(args.project + "/libavcodec/" + td):
        #             os.remove(args.project + "/libavcodec/" + td)
        #         elif os.path.exists(args.project + "/libavformat/" + td):
        #             os.remove(args.project + "/libavformat/" + td)
        #         else:
        #             print("[-] File: {} could not be found in source tree; skipping.".format(td))
        #     print("[+] Finished deleting source files")
    elif "rav1e" in args.project:
        print("[+] Experimental feature: running on Rust-based project")

        feature = args.feature[0]

        makeRust(args.project, feature, "yes", args.tests)
        makeRust(args.project, feature, "no", args.tests)

        # Make one file with the `diff` of coverage info.
        diffs = makeDiffs(home + "/coverage_files_WITH_" + feature + "_yes",
            home + "/coverage_files_WITH_" + feature + "_no", feature)
    elif "aom" in args.project:
        # libaom uses all-caps names.
        feature = args.feature[0].upper()

        # Compile with feature enabled.
        makeAOM(args.project, feature, "yes", args.tests)
        # Compile with feature disabled.
        makeAOM(args.project, feature, "no", args.tests)

        # Make one file with the `diff` of coverage info.
        diffs = makeDiffs(home + "/coverage_files_WITH_" + feature + "_yes",
            home + "/coverage_files_WITH_" + feature + "_no", feature)
    elif "DDS" in args.project:
        # Compile with feature enabled.
        makeDDS(args.project, args.feature[0], "yes", args.tests)
        # Compile with feature disabled.
        makeDDS(args.project, args.feature[0], "no", args.tests)

        # Make one file with the `diff` of coverage info.
        diffs = makeDiffs(home + "/coverage_files_WITH_" + args.feature[0] + "_yes",
            home + "/coverage_files_WITH_" + args.feature[0] + "_no", args.feature[0])
    elif "azure" in args.project:
        # Compile with feature enabled.
        makeCM(args.project, args.feature[0], "yes", args.tests)
        # Compile with feature disabled.
        makeCM(args.project, args.feature[0], "no", args.tests)
        # TODO: make diffs.
    elif "quiche" in args.project:
        print("[+] Experimental feature: running on Rust-based project")

        feature = args.feature[0]

        makeRust(args.project, feature, "yes", args.tests)
        makeRust(args.project, feature, "no", args.tests)

        # Make one file with the `diff` of coverage info.
        diffs = makeDiffs(home + "/coverage_files_WITH_" + feature + "_yes",
            home + "/coverage_files_WITH_" + feature + "_no", feature)
    else:
        print("[-] Target currently unsupported!")
        sys.exit(1)
    
    if args.extract:
        extractFeatures(diffs)
        print("[+] Attempting to open with Firefox...")
        p = subprocess.Popen(["firefox", "./report.html"])
        p.wait()

    sys.exit(0)
