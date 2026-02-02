import os
import json
import subprocess
from pathlib import Path
from typing import List, Dict, Optional

class CodeAnalyzer:
    """
    Outils d'analyse statique de code
    """
    
    @staticmethod
    def run_pylint(file_path: str) -> Dict:
        """Exécute pylint sur un fichier et retourne les résultats structurés
        
        Args:
            file_path: Chemin du fichier à analyser
            
        Returns:
            Dict: {
                'score': float,           # Score Pylint (0-10)
                'raw_output': str,        # Sortie brute stderr
                'messages': List[Dict],   # Messages JSON structurés
                'success': bool           # True si pylint a pu s'exécuter
            }
        """
        try:
            # Exécution pylint avec format texte pour obtenir le score
            result = subprocess.run(
                ['pylint', file_path, '--output-format=text'],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            # Extraire le score de stdout (format texte)
            combined_output = result.stdout + result.stderr
            score = CodeAnalyzer._extract_pylint_score(combined_output)
            
            # Exécution séparée pour les messages JSON
            json_result = subprocess.run(
                ['pylint', file_path, '--output-format=json'],
                capture_output=True,
                text=True,
                timeout=30
            )
            
            # Parser les messages JSON
            pylint_messages = []
            if json_result.stdout:
                try:
                    pylint_messages = json.loads(json_result.stdout)
                except json.JSONDecodeError:
                    pass
            
            return {
                'score': score,
                'raw_output': combined_output,
                'messages': pylint_messages,
                'success': True
            }
            
        except subprocess.TimeoutExpired:
            return {
                'score': 0.0,
                'raw_output': 'Timeout exceeded (>30s)',
                'messages': [],
                'success': False
            }
        except FileNotFoundError:
            return {
                'score': 0.0,
                'raw_output': 'Pylint not installed',
                'messages': [],
                'success': False
            }
        except Exception as e:
            return {
                'score': 0.0,
                'raw_output': f'Error: {str(e)}',
                'messages': [],
                'success': False
            }
    
    @staticmethod
    def _extract_pylint_score(stderr_output: str) -> float:
        """Extrait le score Pylint de la sortie stderr
        
        Args:
            stderr_output: Sortie stderr de pylint
            
        Returns:
            float: Score entre 0 et 10, ou 0.0 si non trouvé
        """
        if not stderr_output:
            return 0.0
        
        for line in stderr_output.split('\n'):
            if 'rated at' in line.lower():
                try:
                    # Format: "Your code has been rated at 7.50/10"
                    score_part = line.split('rated at')[1].split('/')[0].strip()
                    return float(score_part)
                except (IndexError, ValueError):
                    pass
        
        return 0.0
    
    @staticmethod
    def run_pylint_text(file_path: str) -> float:
        """Version simple: retourne uniquement le score Pylint
        
        Args:
            file_path: Chemin du fichier à analyser
            
        Returns:
            float: Score Pylint (0-10)
        """
        result = subprocess.run(
            ['pylint', file_path, '--output-format=text'],
            capture_output=True,
            text=True
        )
        
        return CodeAnalyzer._extract_pylint_score(result.stdout)
    
    @staticmethod
    def count_lines(file_path: str) -> Dict[str, int]:
        """Compte les lignes de code, commentaires, et lignes vides
        
        Args:
            file_path: Chemin du fichier à analyser
            
        Returns:
            Dict: {
                'total': int,
                'code': int,
                'comments': int,
                'blank': int
            }
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            total = len(lines)
            blank = sum(1 for line in lines if line.strip() == '')
            comments = sum(1 for line in lines if line.strip().startswith('#'))
            code = total - blank - comments
            
            return {
                'total': total,
                'code': code,
                'comments': comments,
                'blank': blank
            }
        except Exception:
            return {'total': 0, 'code': 0, 'comments': 0, 'blank': 0}
    
    @staticmethod
    def check_syntax(file_path: str) -> Dict:
        """Vérifie la syntaxe Python avec compile()
        
        Args:
            file_path: Chemin du fichier à vérifier
            
        Returns:
            Dict: {
                'valid': bool,
                'error': str or None,
                'line': int or None
            }
        """
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                code = f.read()
            
            compile(code, file_path, 'exec')
            return {'valid': True, 'error': None, 'line': None}
            
        except SyntaxError as e:
            return {
                'valid': False,
                'error': str(e.msg),
                'line': e.lineno
            }
        except Exception as e:
            return {
                'valid': False,
                'error': str(e),
                'line': None
            }
