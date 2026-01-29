import os
import subprocess
from typing import Dict, List
from mistralai import Mistral
from src.utils.logger import log_experiment, ActionType
from src.tools.file_operations import FileOperations


class JudgeAgent:
    """Agent Judge - Generates tests, executes them, and validates code quality"""
    
    # Tolerance threshold: if pass rate >= this value, consider it acceptable
    PASS_RATE_THRESHOLD = 0.90  # 90% pass rate is acceptable
    MIN_TESTS_FOR_TOLERANCE = 10  # Need at least this many tests to apply tolerance
    
    def __init__(self, model_name: str = "mistral-small-latest"):
        api_key = os.getenv("MISTRAL_API_KEY")
        if not api_key:
            raise ValueError("❌ MISTRAL_API_KEY non trouvée dans .env")
        
        self.client = Mistral(api_key=api_key)
        self.model_name = model_name
        self.name = "Judge"
        print(f"✅ {self.name} initialisé avec modèle: {self.model_name}")
    
    def generate_tests(self, file_path: str) -> Dict:
        """Generate pytest test cases for the given file using LLM
        
        Args:
            file_path: Path to the Python file to test
            
        Returns:
            Dict: {
                'success': bool,
                'test_file': str (path to generated test file),
                'error': str or None
            }
        """
        print(f"🧪 Generating tests for {file_path}...")
        
        # Read the source code
        try:
            source_code = FileOperations.read_file(file_path)
        except Exception as e:
            return {'success': False, 'test_file': None, 'error': str(e)}
        
        # Build prompt for test generation
        prompt = self._build_test_prompt(file_path, source_code)
        
        try:
            response = self.client.chat.complete(
                model=self.model_name,
                messages=[{"role": "user", "content": prompt}]
            )
            
            raw_response = response.choices[0].message.content
            test_code = self._extract_code(raw_response)
            
            if not test_code.strip():
                raise ValueError("LLM generated empty test code")
            
            # Determine test file path
            base_name = os.path.basename(file_path)
            test_file_name = f"test_{base_name}"
            test_file_path = os.path.join(os.path.dirname(file_path), test_file_name)
            
            # Write test file
            FileOperations.write_file(test_file_path, test_code)
            
            # Log the generation
            log_experiment(
                agent_name=self.name,
                model_used=self.model_name,
                action=ActionType.GENERATION,
                details={
                    "input_prompt": prompt,
                    "output_response": raw_response,
                    "source_file": file_path,
                    "test_file": test_file_path
                },
                status="SUCCESS"
            )
            
            print(f"✅ Tests generated: {test_file_path}")
            return {'success': True, 'test_file': test_file_path, 'error': None}
            
        except Exception as e:
            error_msg = str(e)
            print(f"❌ Test generation failed: {error_msg}")
            
            log_experiment(
                agent_name=self.name,
                model_used=self.model_name,
                action=ActionType.GENERATION,
                details={
                    "input_prompt": prompt,
                    "output_response": error_msg,
                    "source_file": file_path,
                    "error": error_msg
                },
                status="FAILURE"
            )
            
            return {'success': False, 'test_file': None, 'error': error_msg}
    
    def run_tests(self, test_file: str, source_file: str = None) -> Dict:
        """Execute pytest on the test file and parse results
        
        Args:
            test_file: Path to the pytest test file
            source_file: Path to the source file being tested (for LLM analysis)
            
        Returns:
            Dict: {
                'success': bool,
                'passed': int,
                'failed': int,
                'errors': int,
                'output': str (raw pytest output),
                'error_logs': str (failure details for Fixer),
                'fix_instructions': list (structured instructions for Fixer)
            }
        """
        print(f"🔬 Running tests: {test_file}...")
        
        try:
            # Run pytest with verbose output
            # Use absolute path to avoid cwd issues
            abs_test_file = os.path.abspath(test_file)
            result = subprocess.run(
                ['pytest', abs_test_file, '-v', '--tb=short'],
                capture_output=True,
                text=True,
                timeout=60
            )
            
            output = result.stdout + result.stderr
            
            # Parse results
            parsed = self._parse_pytest_output(output)
            
            success = parsed['failed'] == 0 and parsed['errors'] == 0
            
            # Build proper prompt for logging (consistent with Auditor/Fixer)
            analysis_prompt = self._build_test_analysis_prompt(test_file, output, source_file)
            
            # Log the test execution with proper prompt format
            log_experiment(
                agent_name=self.name,
                model_used="pytest",
                action=ActionType.DEBUG,
                details={
                    "input_prompt": analysis_prompt,
                    "output_response": output,
                    "test_file": test_file,
                    "tests_passed": parsed['passed'],
                    "tests_failed": parsed['failed'],
                    "tests_errors": parsed['errors']
                },
                status="SUCCESS" if success else "FAILURE"
            )
            
            if success:
                print(f"✅ All tests passed! ({parsed['passed']} tests)")
            else:
                print(f"❌ Tests failed: {parsed['failed']} failed, {parsed['errors']} errors")
            
            # Extract structured error logs and fix instructions
            error_logs = self._extract_error_logs(output) if not success else ""
            fix_instructions = self._analyze_failures_for_fixer(output, source_file) if not success else []
            
            return {
                'success': success,
                'passed': parsed['passed'],
                'failed': parsed['failed'],
                'errors': parsed['errors'],
                'output': output,
                'error_logs': error_logs,
                'fix_instructions': fix_instructions
            }
            
        except subprocess.TimeoutExpired:
            error_msg = "Pytest timeout (>60s)"
            print(f"❌ {error_msg}")
            
            timeout_prompt = f"""ANALYSE D'EXÉCUTION DE TESTS
FICHIER TEST: {test_file}
COMMANDE: pytest {test_file} -v --tb=short
RÉSULTAT: TIMEOUT (>60 secondes)

Le fichier de test a pris trop de temps à s'exécuter, indiquant possiblement:
- Une boucle infinie dans le code source
- Des tests avec des opérations très lourdes
- Un deadlock ou une attente de ressource"""
            
            log_experiment(
                agent_name=self.name,
                model_used="pytest",
                action=ActionType.DEBUG,
                details={
                    "input_prompt": timeout_prompt,
                    "output_response": error_msg,
                    "test_file": test_file
                },
                status="FAILURE"
            )
            
            return {
                'success': False,
                'passed': 0,
                'failed': 0,
                'errors': 1,
                'output': error_msg,
                'error_logs': error_msg,
                'fix_instructions': [{
                    'severity': 'HIGH',
                    'type': 'BUG',
                    'description': 'Les tests ont timeout (>60s). Vérifier les boucles infinies ou opérations bloquantes.',
                    'suggestion': 'Vérifier les boucles while, les appels récursifs, et les opérations I/O dans le code source.'
                }]
            }
            
        except Exception as e:
            error_msg = str(e)
            print(f"❌ Test execution failed: {error_msg}")
            
            exception_prompt = f"""ANALYSE D'EXÉCUTION DE TESTS
FICHIER TEST: {test_file}
COMMANDE: pytest {test_file} -v --tb=short
RÉSULTAT: ERREUR D'EXÉCUTION

Exception rencontrée: {error_msg}"""
            
            log_experiment(
                agent_name=self.name,
                model_used="pytest",
                action=ActionType.DEBUG,
                details={
                    "input_prompt": exception_prompt,
                    "output_response": error_msg,
                    "test_file": test_file
                },
                status="FAILURE"
            )
            
            return {
                'success': False,
                'passed': 0,
                'failed': 0,
                'errors': 1,
                'output': error_msg,
                'error_logs': error_msg,
                'fix_instructions': [{
                    'severity': 'HIGH',
                    'type': 'BUG',
                    'description': f'Erreur d\'exécution des tests: {error_msg}',
                    'suggestion': 'Vérifier que le code source est syntaxiquement correct et que toutes les dépendances sont importables.'
                }]
            }
    
    def judge(self, file_path: str, regenerate_tests: bool = True) -> Dict:
        """Main entry point: generate tests (if needed) and run them
        
        Args:
            file_path: Path to the Python file to judge
            regenerate_tests: If True, always generate new tests
            
        Returns:
            Dict: {
                'success': bool,
                'verdict': str ('PASS' or 'FAIL'),
                'test_results': dict,
                'error_logs': str (for Fixer if failed),
                'fix_instructions': list (structured instructions for Fixer)
            }
        """
        print(f"\n{'='*60}")
        print(f"⚖️  JUDGE EVALUATING: {file_path}")
        print(f"{'='*60}\n")
        
        # Determine test file path
        base_name = os.path.basename(file_path)
        test_file_name = f"test_{base_name}"
        test_file_path = os.path.join(os.path.dirname(file_path), test_file_name)
        
        # Generate tests if needed
        if regenerate_tests or not os.path.exists(test_file_path):
            gen_result = self.generate_tests(file_path)
            if not gen_result['success']:
                return {
                    'success': False,
                    'verdict': 'FAIL',
                    'test_results': None,
                    'error_logs': f"Test generation failed: {gen_result['error']}",
                    'fix_instructions': [{
                        'severity': 'HIGH',
                        'type': 'BUG',
                        'description': f"Échec de génération des tests: {gen_result['error']}",
                        'suggestion': 'Vérifier que le code source est valide et peut être importé.'
                    }]
                }
            test_file_path = gen_result['test_file']
        
        # Run the tests (pass source file for better analysis)
        test_results = self.run_tests(test_file_path, source_file=file_path)
        
        verdict = 'PASS' if test_results['success'] else 'FAIL'
        
        print(f"\n{'='*60}")
        print(f"⚖️  VERDICT: {verdict}")
        print(f"{'='*60}\n")
        
        return {
            'success': test_results['success'],
            'verdict': verdict,
            'test_results': test_results,
            'error_logs': test_results.get('error_logs', ''),
            'fix_instructions': test_results.get('fix_instructions', [])
        }
    
    def _build_test_prompt(self, file_path: str, source_code: str) -> str:
        """Build the prompt for test generation - fully dynamic based on file path"""
        
        # Extract module name from file path for imports
        base_name = os.path.basename(file_path).replace('.py', '')
        dir_name = os.path.basename(os.path.dirname(os.path.abspath(file_path)))
        
        # Extract function/class names from source code for dynamic import suggestion
        import re
        function_names = re.findall(r'^def\s+(\w+)\s*\(', source_code, re.MULTILINE)
        class_names = re.findall(r'^class\s+(\w+)\s*[:\(]', source_code, re.MULTILINE)
        
        # Build dynamic import statement
        all_names = function_names + class_names
        if all_names:
            specific_imports = ', '.join(all_names)
            import_statement = f"from {dir_name}.{base_name} import {specific_imports}"
        else:
            import_statement = f"from {dir_name}.{base_name} import *"
        
        return f"""Tu es un ingénieur QA senior spécialisé dans les tests unitaires Python. Ta mission est de générer une suite de tests pytest exhaustive et professionnelle pour valider le code source fourni.

================================================================================
INFORMATIONS DU MODULE
================================================================================
FICHIER: {file_path}
MODULE: {base_name}
DOSSIER: {dir_name}
IMPORT: {import_statement}

ÉLÉMENTS DÉTECTÉS:
- Fonctions: {', '.join(function_names) if function_names else 'Aucune'}
- Classes: {', '.join(class_names) if class_names else 'Aucune'}

================================================================================
CODE SOURCE
================================================================================
```python
{source_code}
```

================================================================================
DIRECTIVES DE GÉNÉRATION
================================================================================

1. **STRUCTURE OBLIGATOIRE**:
   - Fichier autonome exécutable avec pytest
   - Configuration PYTHONPATH pour les imports
   - Convention de nommage: test_<fonction>_<scenario>
   - Docstring pour chaque test

2. **COUVERTURE DE TESTS** (pour chaque fonction/méthode):
   - Cas nominaux: valeurs typiques, comportement normal
   - Cas limites: zéro, négatifs, listes vides, None, grandes valeurs
   - Cas d'erreurs: exceptions attendues avec pytest.raises()

3. **RÈGLES DE QUALITÉ**:
   - Tests indépendants sans état partagé
   - Une assertion logique par test
   - pytest.approx() pour les comparaisons flottantes
   - Noms descriptifs en anglais

4. **TEMPLATE D'IMPORT**:
```python
import pytest
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
{import_statement}
```

================================================================================
RÈGLES CRITIQUES - LIRE ATTENTIVEMENT
================================================================================

**IMPORTANT**: Les tests doivent correspondre au COMPORTEMENT RÉEL du code fourni:

1. **Lire attentivement le code source** avant de générer les tests
2. **Ne pas inventer de comportements** - tester uniquement ce que le code fait réellement
3. **Si une fonction retourne None pour cas d'erreur**, ne pas tester qu'elle lève une exception
4. **Si une fonction crée automatiquement des clés manquantes**, ne pas tester KeyError
5. **Si une fonction retourne une liste vide pour entrée vide**, tester ce comportement exact
6. **Vérifier les docstrings et annotations** pour comprendre le comportement attendu

EXEMPLE DE MAUVAIS TEST (à éviter):
```python
# Si le code fait: return data.get(key, None)
def test_missing_key():
    with pytest.raises(KeyError):  # FAUX - le code retourne None, pas KeyError
        get_value(data, "missing")
```

EXEMPLE DE BON TEST:
```python
# Si le code fait: return data.get(key, None)
def test_missing_key():
    result = get_value(data, "missing")
    assert result is None  # CORRECT - correspond au comportement réel
```

================================================================================
FORMAT DE SORTIE
================================================================================
- Code Python uniquement, pas de markdown, pas d'explications
- Exécutable directement avec: pytest fichier.py -v
- Minimum 3 tests par fonction détectée

Le code doit commencer directement par les imports.
"""
    
    def _extract_code(self, response: str) -> str:
        """Extract Python code from LLM response"""
        if "```python" in response:
            return response.split("```python")[1].split("```")[0].strip()
        elif "```" in response:
            return response.split("```")[1].split("```")[0].strip()
        return response.strip()
    
    def _parse_pytest_output(self, output: str) -> Dict:
        """Parse pytest output to extract pass/fail counts"""
        import re
        
        passed = 0
        failed = 0
        errors = 0
        
        # Check for collection errors (import failures, syntax errors)
        if 'ERROR' in output and 'collecting' in output.lower():
            # Collection failed - treat as error
            return {
                'passed': 0,
                'failed': 0,
                'errors': 1,
                'collection_error': True
            }
        
        # Check for "no tests ran" or "0 items collected"
        if 'no tests ran' in output.lower() or '0 items collected' in output.lower():
            return {
                'passed': 0,
                'failed': 0,
                'errors': 1,
                'collection_error': True
            }
        
        # Look for summary line like "5 failed, 9 passed" or "9 passed, 5 failed"
        # Match patterns: "X passed", "X failed", "X error"
        for line in output.split('\n'):
            # Look for the final summary line (contains "passed" or "failed" with numbers)
            if '=====' in line and ('passed' in line or 'failed' in line):
                # Extract "N passed"
                passed_match = re.search(r'(\d+)\s+passed', line)
                if passed_match:
                    passed = int(passed_match.group(1))
                
                # Extract "N failed"
                failed_match = re.search(r'(\d+)\s+failed', line)
                if failed_match:
                    failed = int(failed_match.group(1))
                
                # Extract "N error"
                error_match = re.search(r'(\d+)\s+error', line)
                if error_match:
                    errors = int(error_match.group(1))
        
        # If we found nothing (0 passed, 0 failed, 0 errors), something went wrong
        if passed == 0 and failed == 0 and errors == 0:
            # Check if there were any test functions actually collected
            collected_match = re.search(r'collected\s+(\d+)\s+item', output)
            if collected_match:
                collected = int(collected_match.group(1))
                if collected > 0:
                    # Tests were collected but we couldn't parse results - assume error
                    errors = 1
            else:
                # No collection info found - treat as error
                errors = 1
        
        return {
            'passed': passed,
            'failed': failed,
            'errors': errors
        }
    
    def _extract_error_logs(self, output: str) -> str:
        """Extract relevant error information from pytest output for the Fixer"""
        error_lines = []
        capture = False
        
        for line in output.split('\n'):
            # Start capturing at FAILURES or ERRORS section
            if 'FAILURES' in line or 'ERRORS' in line or 'ERROR' in line:
                capture = True
            
            # Stop at short test summary
            if 'short test summary' in line.lower():
                capture = False
            
            if capture:
                error_lines.append(line)
        
        # If no specific failures found, return last 30 lines
        if not error_lines:
            return '\n'.join(output.split('\n')[-30:])
        
        return '\n'.join(error_lines)
    
    def _build_test_analysis_prompt(self, test_file: str, output: str, source_file: str = None) -> str:
        """Build a proper prompt for logging test analysis (consistent with Auditor/Fixer format)"""
        
        return f"""ANALYSE D'EXÉCUTION DE TESTS PYTEST
================================================================================

FICHIER DE TESTS: {test_file}
FICHIER SOURCE: {source_file or 'Non spécifié'}
COMMANDE: pytest {test_file} -v --tb=short

================================================================================
OBJECTIF
================================================================================
Exécuter la suite de tests unitaires et analyser les résultats pour:
1. Valider que le code source fonctionne correctement
2. Identifier les tests qui échouent
3. Extraire les messages d'erreur pour guider les corrections

================================================================================
SORTIE PYTEST (TRONQUÉE)
================================================================================
{output[:3000]}{'...[TRONQUÉ]' if len(output) > 3000 else ''}
"""
    
    def _analyze_failures_for_fixer(self, output: str, source_file: str = None) -> list:
        """Analyze test failures and create detailed fix instructions for Fixer agent
        
        Args:
            output: Raw pytest output
            source_file: Path to the source file being tested
            
        Returns:
            list: List of structured fix instructions with detailed error info
        """
        import re
        
        fix_instructions = []
        
        # Split output into individual test failure sections
        # Each failure starts with "_____ test_name _____" and contains the full traceback
        failure_sections = re.split(r'_{3,}\s*(test_\w+)\s*_{3,}', output)
        
        # Process pairs of (test_name, failure_content)
        for i in range(1, len(failure_sections), 2):
            if i + 1 < len(failure_sections):
                test_name = failure_sections[i]
                failure_content = failure_sections[i + 1]
                
                # Extract the assertion or error details
                error_info = self._parse_failure_details(test_name, failure_content)
                if error_info:
                    fix_instructions.append(error_info)
        
        # Also check short test summary for any missed failures
        summary_pattern = r'FAILED\s+[\w./]+::(test_\w+)\s*[-–]\s*(\w+(?:Error|Exception)?):?\s*(.*)'
        summary_failures = re.findall(summary_pattern, output)
        
        # Add any failures from summary that we didn't already capture
        existing_tests = {f.get('test_name') for f in fix_instructions}
        for test_name, error_type, error_msg in summary_failures:
            if test_name not in existing_tests:
                fix_instructions.append({
                    'severity': 'HIGH',
                    'type': 'BUG',
                    'test_name': test_name,
                    'error_type': error_type,
                    'description': f"Test '{test_name}' a échoué avec {error_type}",
                    'suggestion': self._generate_fix_suggestion(test_name, error_type, error_msg),
                    'error_details': error_msg.strip()[:500]
                })
        
        # If still no structured failures found, use raw error logs
        if not fix_instructions and ('FAILED' in output or 'ERROR' in output):
            error_section = self._extract_error_logs(output)
            fix_instructions.append({
                'severity': 'HIGH',
                'type': 'BUG',
                'test_name': 'unknown',
                'error_type': 'TestFailure',
                'description': 'Des tests ont échoué. Voir les détails complets ci-dessous.',
                'suggestion': f"Analyser les erreurs et corriger le code:\n{error_section}"
            })
        
        return fix_instructions
    
    def _parse_failure_details(self, test_name: str, failure_content: str) -> dict:
        """Parse a single test failure section to extract detailed information"""
        import re
        
        result = {
            'severity': 'HIGH',
            'type': 'BUG',
            'test_name': test_name,
            'error_type': 'AssertionError',
            'description': '',
            'suggestion': '',
            'test_code': '',
            'expected': '',
            'actual': '',
            'error_details': ''
        }
        
        # Extract the test code (lines starting with > )
        test_code_lines = re.findall(r'>\s+(.+)', failure_content)
        if test_code_lines:
            result['test_code'] = '\n'.join(test_code_lines)
        
        # Extract assertion error details
        # Pattern: "AssertionError: assert X == Y" or "E       assert X == Y"
        assertion_match = re.search(r'(?:AssertionError:|E\s+assert)\s*(.+)', failure_content)
        if assertion_match:
            result['error_details'] = assertion_match.group(1).strip()[:500]
        
        # Extract expected vs actual from pytest output
        # Pattern: "E       assert 'actual' == 'expected'"
        comparison_match = re.search(r"assert\s+(.+?)\s*==\s*(.+?)(?:\n|$)", failure_content)
        if comparison_match:
            result['actual'] = comparison_match.group(1).strip()[:200]
            result['expected'] = comparison_match.group(2).strip()[:200]
        
        # Also look for "where X = function(...)" to understand what was called
        where_match = re.search(r'where\s+.+?=\s*(\w+)\(([^)]*)\)', failure_content)
        function_called = None
        if where_match:
            function_called = where_match.group(1)
            args = where_match.group(2)
            result['function_called'] = function_called
            result['function_args'] = args
        
        # Detect error type from content
        if 'KeyError' in failure_content:
            result['error_type'] = 'KeyError'
        elif 'TypeError' in failure_content:
            result['error_type'] = 'TypeError'
        elif 'ValueError' in failure_content:
            result['error_type'] = 'ValueError'
        elif 'AttributeError' in failure_content:
            result['error_type'] = 'AttributeError'
        elif 'IndexError' in failure_content:
            result['error_type'] = 'IndexError'
        
        # Build detailed description
        desc_parts = [f"Test '{test_name}' a échoué"]
        if result['test_code']:
            desc_parts.append(f"Code du test: {result['test_code'][:200]}")
        if result['expected'] and result['actual']:
            desc_parts.append(f"Attendu: {result['expected']}")
            desc_parts.append(f"Obtenu: {result['actual']}")
        if result['error_details']:
            desc_parts.append(f"Erreur: {result['error_details']}")
        
        result['description'] = '\n'.join(desc_parts)
        
        # Build specific suggestion
        suggestion_parts = []
        if function_called:
            suggestion_parts.append(f"Vérifier la fonction '{function_called}'")
        if result['expected'] and result['actual']:
            suggestion_parts.append(f"La fonction retourne {result['actual']} mais devrait retourner {result['expected']}")
        suggestion_parts.append(self._generate_fix_suggestion(test_name, result['error_type'], result['error_details']))
        
        result['suggestion'] = '\n'.join(suggestion_parts)
        
        return result
    
    def evaluate_with_tolerance(self, test_results: Dict) -> Dict:
        """Evaluate test results with tolerance - used for final verdict after max iterations
        
        This method applies a tolerance threshold: if the pass rate is high enough
        (e.g., 90%+ with at least 10 tests), we consider it acceptable even with
        some failing tests.
        
        Args:
            test_results: Dict with 'passed', 'failed', 'errors' counts
            
        Returns:
            Dict: {
                'acceptable': bool,
                'pass_rate': float,
                'passed': int,
                'failed': int,
                'reason': str
            }
        """
        if not test_results:
            return {
                'acceptable': False,
                'pass_rate': 0.0,
                'passed': 0,
                'failed': 0,
                'reason': 'Aucun résultat de test disponible'
            }
        
        passed = test_results.get('passed', 0)
        failed = test_results.get('failed', 0)
        errors = test_results.get('errors', 0)
        
        total = passed + failed + errors
        
        if total == 0:
            return {
                'acceptable': False,
                'pass_rate': 0.0,
                'passed': 0,
                'failed': 0,
                'reason': 'Aucun test exécuté'
            }
        
        pass_rate = passed / total
        
        # Check if we have enough tests and high enough pass rate
        if total >= self.MIN_TESTS_FOR_TOLERANCE and pass_rate >= self.PASS_RATE_THRESHOLD:
            return {
                'acceptable': True,
                'pass_rate': pass_rate,
                'passed': passed,
                'failed': failed,
                'reason': f'Taux de réussite acceptable: {pass_rate:.1%} ({passed}/{total} tests passés)'
            }
        elif total < self.MIN_TESTS_FOR_TOLERANCE and pass_rate >= self.PASS_RATE_THRESHOLD:
            return {
                'acceptable': True,
                'pass_rate': pass_rate,
                'passed': passed,
                'failed': failed,
                'reason': f'Taux de réussite acceptable: {pass_rate:.1%} ({passed}/{total} tests)'
            }
        else:
            return {
                'acceptable': False,
                'pass_rate': pass_rate,
                'passed': passed,
                'failed': failed,
                'reason': f'Taux de réussite insuffisant: {pass_rate:.1%} (seuil: {self.PASS_RATE_THRESHOLD:.0%})'
            }
    
    def _generate_fix_suggestion(self, test_name: str, error_type: str, error_msg: str) -> str:
        """Generate specific fix suggestions based on error type"""
        
        suggestions = {
            'AssertionError': f"La valeur retournée ne correspond pas à l'attendu. Vérifier la logique de la fonction testée par '{test_name}'.",
            'TypeError': f"Type incorrect détecté. Vérifier les types des paramètres et valeurs de retour.",
            'ValueError': f"Valeur invalide. Vérifier la validation des entrées et les cas limites.",
            'AttributeError': f"Attribut manquant. Vérifier que l'objet a bien l'attribut ou méthode appelée.",
            'KeyError': f"Clé manquante dans un dictionnaire. Vérifier les clés utilisées.",
            'IndexError': f"Index hors limites. Vérifier les accès aux listes/tableaux.",
            'ZeroDivisionError': f"Division par zéro. Ajouter une vérification avant la division.",
            'ImportError': f"Import échoué. Vérifier que le module existe et est accessible.",
            'NameError': f"Variable non définie. Vérifier l'orthographe et la portée des variables."
        }
        
        base_suggestion = suggestions.get(error_type, f"Corriger l'erreur {error_type} dans la fonction testée.")
        
        # Add context from error message if available
        if error_msg:
            base_suggestion += f"\nDétail: {error_msg[:300]}"
        
        return base_suggestion
