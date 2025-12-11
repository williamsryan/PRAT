"""
Report generation module for PRAT.

This module handles generating HTML reports and DOT graphs for visualization
of feature extraction results.
"""

import os
import subprocess
import shutil
from typing import Optional
from .extraction import ExtractionResult


def generate_html_report(extraction_result: ExtractionResult, 
                        feature: str,
                        output_path: str = "report.html") -> str:
    """
    Generate HTML table showing files and removable line counts.
    
    Args:
        extraction_result: Results from feature extraction
        feature: Feature name for report title
        output_path: Path to output HTML file
    
    Returns:
        Path to generated HTML file
    """
    print(f"[+] Generating HTML report: {output_path}")
    
    # HTML template
    html = f"""<!DOCTYPE html>
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
    <h3>Code to Remove for Feature: {feature}</h3>
    <table class="table table-striped" id="scTab">
        <thead>
        <tr>
            <th scope="col">Source File</th>
            <th scope="col">LoC to Remove</th>
        </tr>
        </thead>
        <tbody id="scBody">
"""
    
    # Add rows for each file
    for file_name, count in extraction_result.file_line_counts.items():
        # Check if we have HTML reports for individual files
        report_name = file_name + ".gcov-diff.html"
        report_path = os.path.join("reports", report_name)
        
        if os.path.exists(report_path):
            html += f"""        <tr>
            <td><a href="./reports/{report_name}" target="_blank">{file_name}</a></td>
            <td>{count}</td>
        </tr>
"""
        else:
            html += f"""        <tr>
            <td>{file_name}</td>
            <td>{count}</td>
        </tr>
"""
    
    # Add total row
    html += f"""        <tr>
            <td><b>Total LoC to Remove</b></td>
            <td><b>{extraction_result.total_removable_lines}</b></td>
        </tr>
"""
    
    # Close HTML
    html += """        </tbody>
    </table>
</body>
</html>
"""
    
    # Write HTML file
    with open(output_path, 'w') as f:
        f.write(html)
    
    print(f"[+] HTML report generated: {output_path}")
    return output_path


def generate_dot_graph(extraction_result: ExtractionResult,
                      feature: str = "Feature",
                      output_path: str = "FDG.dot",
                      max_content_length: int = 100) -> str:
    """
    Generate DOT file showing relationships between files and features.
    
    Args:
        extraction_result: Results from feature extraction
        feature: Feature name for graph labels
        output_path: Path to output DOT file
        max_content_length: Maximum length for code content in nodes
    
    Returns:
        Path to generated DOT file
    """
    print(f"[+] Generating DOT graph: {output_path}")
    
    # DOT graph header
    dot = """digraph G {
    graph [fontsize=10 fontname="Verdana" compound=true];
    subgraph cluster_components {
        label="MQTT Components";
        "WebSocket Support";
        "Bridge Support";
        "With Wrap";
        "..."
    }
    subgraph cluster_bridge {
        label="TODO";
"""
    
    # Add nodes for each file with removable code
    for file_name, line_contents in extraction_result.file_line_content.items():
        if not line_contents:
            continue
        
        # Combine line contents (truncate if too long)
        combined_content = "\\n".join(line_contents)
        if len(combined_content) > max_content_length:
            combined_content = combined_content[:max_content_length - 3] + "..."
        
        # Escape special characters for DOT format
        combined_content = combined_content.replace('"', '\\"')
        combined_content = combined_content.replace('\n', '\\n')
        
        # Add edge from file to its removable code
        dot += f'    "{file_name}" -> "{combined_content}";\n'
    
    # DOT graph footer
    dot += """    }
}
"""
    
    # Write DOT file
    with open(output_path, 'w') as f:
        f.write(dot)
    
    print(f"[+] DOT graph generated: {output_path}")
    return output_path


def generate_html_diffs(diff_dir: str, reports_dir: str = "reports") -> bool:
    """
    Generate HTML-formatted diff files using pygmentize.
    
    Args:
        diff_dir: Directory containing diff files
        reports_dir: Directory to store HTML reports
    
    Returns:
        True if successful, False otherwise
    """
    # Check if pygmentize is available
    if not shutil.which("pygmentize"):
        print("[-] `pygments` is not available. Install with: `pip install Pygments`")
        return False
    
    print("[+] Generating HTML assets...")
    
    # Ensure reports directory exists
    os.makedirs(reports_dir, exist_ok=True)
    
    # Process each diff file
    success = True
    for diff_file in os.listdir(diff_dir):
        if not os.path.isfile(os.path.join(diff_dir, diff_file)):
            continue
        
        input_path = os.path.join(diff_dir, diff_file)
        output_path = os.path.join(reports_dir, diff_file + "-diff.html")
        
        try:
            subprocess.run(
                ["pygmentize", "-l", "diff", "-f", "html", "-O", "full", 
                 "-o", output_path, input_path],
                check=True,
                stderr=subprocess.PIPE
            )
        except subprocess.CalledProcessError as e:
            print(f"[-] Error generating HTML for {diff_file}: {e}")
            success = False
            continue
    
    return success
