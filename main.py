import argparse
import sys
import os
from dotenv import load_dotenv
from src.utils.logger import log_experiment, ActionType
from src.agents.auditor import AuditorAgent
from src.agents.fixer import FixerAgent
from src.agents.judge import JudgeAgent
from src.tools.file_operations import FileOperations
from src.tools.code_analyzer import CodeAnalyzer

load_dotenv()

# Configuration
MAX_ITERATIONS = 10


def run_swarm(target_dir: str) -> dict:
    """
    Main orchestration loop: Auditor → Fixer → Judge → (repeat if fail)
    
    Args:
        target_dir: Directory containing Python files to refactor
        
    Returns:
        dict: Final results summary
    """
    print("=" * 70)
    print("🐝 THE REFACTORING SWARM - STARTING MISSION")
    print("=" * 70)
    print(f"📁 Target: {target_dir}")
    print(f"🔄 Max iterations: {MAX_ITERATIONS}")
    print("=" * 70 + "\n")
    
    # Log startup
    log_experiment(
        agent_name="Orchestrator",
        model_used="system",
        action=ActionType.ANALYSIS,
        details={
            "input_prompt": f"Start refactoring swarm on {target_dir}",
            "output_response": "Initializing agents...",
            "target_dir": target_dir,
            "max_iterations": MAX_ITERATIONS
        },
        status="SUCCESS"
    )
    
    # Initialize agents
    print("🔧 Initializing agents...")
    try:
        auditor = AuditorAgent()
        fixer = FixerAgent()
        judge = JudgeAgent()
    except Exception as e:
        print(f"❌ Failed to initialize agents: {e}")
        return {"success": False, "error": str(e)}
    
    # Get all Python files in target directory
    python_files = FileOperations.get_python_files(target_dir)
    
    if not python_files:
        print(f"⚠️ No Python files found in {target_dir}")
        return {"success": False, "error": "No Python files found"}
    
    print(f"📄 Found {len(python_files)} Python file(s) to process\n")
    
    # Results tracking
    results = {
        "files_processed": 0,
        "files_success": 0,
        "files_failed": 0,
        "details": []
    }
    
    # Process each file
    for file_path in python_files:
        file_result = process_file(file_path, auditor, fixer, judge)
        results["files_processed"] += 1
        results["details"].append(file_result)
        
        if file_result["success"]:
            results["files_success"] += 1
        else:
            results["files_failed"] += 1
    
    # Final summary
    print("\n" + "=" * 70)
    print("🏁 MISSION COMPLETE - FINAL SUMMARY")
    print("=" * 70)
    print(f"📊 Files processed: {results['files_processed']}")
    print(f"✅ Success: {results['files_success']}")
    print(f"❌ Failed: {results['files_failed']}")
    print("=" * 70)
    
    # Log completion
    log_experiment(
        agent_name="Orchestrator",
        model_used="system",
        action=ActionType.ANALYSIS,
        details={
            "input_prompt": "Mission complete",
            "output_response": f"Processed {results['files_processed']} files",
            "files_success": results["files_success"],
            "files_failed": results["files_failed"]
        },
        status="SUCCESS" if results["files_failed"] == 0 else "PARTIAL"
    )
    
    return results


def process_file(file_path: str, auditor: AuditorAgent, fixer: FixerAgent, judge: JudgeAgent) -> dict:
    """
    Process a single file through the refactoring pipeline
    
    Flow: Auditor → Fixer → Judge → (if fail) → Fixer → Judge → repeat
    """
    print("\n" + "=" * 70)
    print(f"📄 PROCESSING: {file_path}")
    print("=" * 70)
    
    # Get initial pylint score
    initial_score = CodeAnalyzer.run_pylint(file_path)["score"]
    print(f"📊 Initial Pylint score: {initial_score}/10")
    
    # =========================================================================
    # PHASE 1: AUDIT (runs once)
    # =========================================================================
    print(f"\n{'─' * 50}")
    print("🔍 PHASE 1: AUDIT")
    print(f"{'─' * 50}")
    
    try:
        audit_result = auditor.analyze_file(file_path)
        print(f"   Found {len(audit_result['issues'])} issues")
    except Exception as e:
        print(f"❌ Audit failed: {e}")
        return {"file": file_path, "success": False, "error": f"Audit failed: {e}"}
    
    # =========================================================================
    # PHASE 2: INITIAL FIX
    # =========================================================================
    print(f"\n{'─' * 50}")
    print("🔧 PHASE 2: INITIAL FIX")
    print(f"{'─' * 50}")
    
    try:
        fixer.apply_fixes(file_path, audit_result)
    except Exception as e:
        print(f"❌ Initial fix failed: {e}")
        return {"file": file_path, "success": False, "error": f"Fix failed: {e}"}
    
    # =========================================================================
    # PHASE 3: JUDGE + SELF-HEALING LOOP
    # =========================================================================
    print(f"\n{'─' * 50}")
    print("⚖️ PHASE 3: JUDGE + SELF-HEALING LOOP")
    print(f"{'─' * 50}")
    
    iteration = 0
    judge_result = None
    
    # First judge run - generate tests
    judge_result = judge.judge(file_path, regenerate_tests=True)
    
    # Self-healing loop
    while not judge_result["success"] and iteration < MAX_ITERATIONS:
        iteration += 1
        current_failed = judge_result['test_results']['failed'] if judge_result['test_results'] else 0
        
        print(f"\n🔄 ITERATION {iteration}/{MAX_ITERATIONS}")
        print(f"   Tests: {judge_result['test_results']['passed']} passed, {current_failed} failed")
        
        # Use structured fix_instructions from Judge with detailed error info
        fix_instructions = judge_result.get('fix_instructions', [])
        
        if fix_instructions:
            # Use the structured instructions directly
            fix_request = {"issues": fix_instructions}
            print(f"   📋 {len(fix_instructions)} fix instruction(s) from Judge")
        else:
            # Fallback to error_logs if no structured instructions
            fix_request = {
                "issues": [{
                    "severity": "HIGH",
                    "type": "BUG",
                    "line": 0,
                    "description": f"Test failures detected:\n{judge_result['error_logs']}",
                    "suggestion": "Analyser les erreurs de tests et corriger le code source."
                }]
            }
            print(f"   📋 Using raw error logs (fallback)")
        
        # Fixer attempts to fix based on test errors
        print(f"   🔧 Fixer attempting repair...")
        try:
            fixer.apply_fixes(file_path, fix_request)
        except Exception as e:
            print(f"   ⚠️ Fix attempt failed: {e}")
            continue
        
        # Judge re-evaluates (don't regenerate tests)
        print(f"   ⚖️ Judge re-evaluating...")
        judge_result = judge.judge(file_path, regenerate_tests=False)
    
    # =========================================================================
    # TOLERANCE CHECK: After max iterations, apply tolerance threshold
    # =========================================================================
    final_success = judge_result["success"]
    tolerance_applied = False
    
    if not final_success and judge_result.get("test_results"):
        # Check if we can accept with tolerance
        tolerance_result = judge.evaluate_with_tolerance(judge_result["test_results"])
        
        if tolerance_result["acceptable"]:
            final_success = True
            tolerance_applied = True
            print(f"\n   🎯 TOLERANCE APPLIED: {tolerance_result['reason']}")
        else:
            print(f"\n   ❌ Tolerance check failed: {tolerance_result['reason']}")
    
    # =========================================================================
    # FINAL RESULTS
    # =========================================================================
    final_score = CodeAnalyzer.run_pylint(file_path)["score"]
    
    print(f"\n{'─' * 50}")
    print("📊 FILE RESULTS")
    print(f"{'─' * 50}")
    print(f"   Initial Pylint: {initial_score}/10")
    print(f"   Final Pylint:   {final_score}/10")
    print(f"   Improvement:    {final_score - initial_score:+.2f}")
    print(f"   Iterations:     {iteration}")
    print(f"   Tests passed:   {judge_result['test_results']['passed'] if judge_result['test_results'] else 0}")
    print(f"   Tests failed:   {judge_result['test_results']['failed'] if judge_result['test_results'] else 0}")
    if tolerance_applied:
        print(f"   Verdict:        ✅ PASS (with tolerance)")
    else:
        print(f"   Verdict:        {'✅ PASS' if final_success else '❌ FAIL'}")
    
    return {
        "file": file_path,
        "success": final_success,
        "initial_score": initial_score,
        "final_score": final_score,
        "iterations": iteration,
        "tests_passed": judge_result["test_results"]["passed"] if judge_result["test_results"] else 0,
        "tests_failed": judge_result["test_results"]["failed"] if judge_result["test_results"] else 0,
        "tolerance_applied": tolerance_applied
    }


def main():
    parser = argparse.ArgumentParser(
        description="The Refactoring Swarm - Autonomous code refactoring system"
    )
    parser.add_argument(
        "--target_dir", 
        type=str, 
        required=True,
        help="Directory containing Python files to refactor"
    )
    args = parser.parse_args()

    # Validate target directory
    if not os.path.exists(args.target_dir):
        print(f"❌ Directory not found: {args.target_dir}")
        sys.exit(1)

    # Run the swarm
    results = run_swarm(args.target_dir)
    
    # Exit code based on results
    if results.get("files_failed", 0) == 0:
        print("\n✅ MISSION_COMPLETE")
        sys.exit(0)
    else:
        print("\n⚠️ MISSION_PARTIAL - Some files failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
