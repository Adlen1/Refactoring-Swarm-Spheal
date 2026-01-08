import os
import json
from typing import Dict, List, Optional
from src.utils.logger import log_experiment, ActionType
from src.tools.file_operations import FileOperations
from src.tools.code_analyzer import CodeAnalyzer
from mistralai import Mistral


class AuditorAgent:
    """Agent Auditeur - Analyse le code et produit un plan de refactoring structuré"""
    
    def __init__(self, model_name: str = "mistral-small-latest"):
        api_key = os.getenv("MISTRAL_API_KEY")
        if not api_key:
            raise ValueError("❌ MISTRAL_API_KEY non trouvée dans .env")
        
        self.client = Mistral(api_key=api_key)
        self.model_name = model_name
        self.name = "Auditor"
        print(f"✅ {self.name} initialisé avec modèle: {self.model_name}")
    
    def analyze_file(self, file_path: str, file_content: str = None) -> Dict:
        """Analyse un fichier Python et produit un plan de refactoring détaillé
        
        Args:
            file_path: Chemin du fichier à analyser
            file_content: Contenu du fichier (optionnel, sera lu si non fourni)
            
        Returns:
            dict: {
                'file_path': str,
                'pylint_score': float,
                'issues': list,
                'refactoring_priority': list,
                'estimated_fixes': int,
                'summary': str
            }
        """
        
        # 1. Lire le fichier si le contenu n'est pas fourni
        if file_content is None:
            try:
                file_content = FileOperations.read_file(file_path)
            except Exception as e:
                return self._create_error_analysis(file_path, f"Lecture impossible: {str(e)}")
        
        # 2. Vérifier la syntaxe Python
        print(f"🔍 Vérification syntaxe de {file_path}...")
        syntax_check = CodeAnalyzer.check_syntax(file_path)
        
        # 3. Exécuter Pylint
        print(f"🔍 Analyse Pylint de {file_path}...")
        pylint_results = CodeAnalyzer.run_pylint(file_path)
        
        if not pylint_results['success']:
            print(f"⚠️ Pylint non disponible, analyse limitée")
        
        # 4. Statistiques du fichier
        line_stats = CodeAnalyzer.count_lines(file_path)
        
        # 5. Construire le prompt enrichi pour le LLM
        prompt = self._build_analysis_prompt(
            file_path=file_path,
            file_content=file_content,
            pylint_results=pylint_results,
            syntax_check=syntax_check,
            line_stats=line_stats
        )
        
        try:
            # 6. Appeler le LLM
            print(f"🤖 Analyse LLM en cours...")
            response = self.client.chat.complete(
                model=self.model_name,
                messages=[
                    {"role": "user", "content": prompt}
                ]
            )
            
            output = response.choices[0].message.content
            
            # 7. Parser la réponse JSON
            result = self._parse_llm_response(output, file_path, pylint_results)
            
            # 8. Log pour l'analyse scientifique (FORMAT STRICT)
            log_experiment(
                agent_name=self.name,
                model_used=self.model_name,
                action=ActionType.ANALYSIS,
                details={
                    "input_prompt": prompt,
                    "output_response": output,
                    "file_analyzed": file_path,
                    "pylint_score": pylint_results['score'],
                    "issues_found": len(result['issues']),
                    "syntax_valid": syntax_check['valid']
                },
                status="SUCCESS"
            )
            
            print(f"✅ Analyse terminée: {len(result['issues'])} problèmes trouvés (Score: {result['pylint_score']}/10)")
            return result
            
        except Exception as e:
            error_msg = f"Erreur LLM: {str(e)}"
            print(f"❌ {error_msg}")
            
            # Log de l'échec
            log_experiment(
                agent_name=self.name,
                model_used=self.model_name,
                action=ActionType.ANALYSIS,
                details={
                    "input_prompt": prompt,
                    "output_response": error_msg,
                    "file_analyzed": file_path
                },
                status="FAILURE"
            )
            
            # Retourner analyse de secours basée sur Pylint
            return self._create_fallback_analysis(file_path, pylint_results, syntax_check, error_msg)
    
    def _build_analysis_prompt(
        self, 
        file_path: str, 
        file_content: str, 
        pylint_results: Dict, 
        syntax_check: Dict,
        line_stats: Dict
    ) -> str:
        """Construit le prompt d'analyse pour le LLM"""
        
        # Informations de contexte
        context = f"""FICHIER: {file_path}
LIGNES DE CODE: {line_stats['code']} | COMMENTAIRES: {line_stats['comments']} | VIDES: {line_stats['blank']}
SYNTAXE VALIDE: {"✅ Oui" if syntax_check['valid'] else f"❌ Non - {syntax_check['error']} (ligne {syntax_check['line']})"}
SCORE PYLINT: {pylint_results['score']}/10
"""
        
        # Messages Pylint (limiter à 15 pour économiser tokens)
        pylint_summary = ""
        if pylint_results['messages']:
            pylint_summary = "\nPRINCIPAUX MESSAGES PYLINT:\n"
            for msg in pylint_results['messages'][:15]:
                pylint_summary += f"- Ligne {msg.get('line', '?')}: [{msg.get('type', 'info')}] {msg.get('message', '')}\n"
        
        prompt = f"""Tu es un expert en analyse de code Python et en refactoring. Analyse ce fichier et produis un plan de refactoring détaillé.

{context}

{pylint_summary}

CODE SOURCE:
```python
{file_content}
```

INSTRUCTIONS:
Analyse le code et identifie TOUS les problèmes dans les catégories suivantes:

1. **BUGS** (HIGH severity): Erreurs qui causent des crashes ou comportements incorrects
   - Division par zéro, index out of range, None handling
   - Erreurs logiques, conditions incorrectes
   - Exceptions non gérées
   - Variables non définies ou mal utilisées

2. **QUALITY** (MEDIUM severity): Problèmes de qualité et maintenabilité
   - Fonctions/classes sans docstrings
   - Noms de variables non descriptifs (a, b, c, x, y)
   - Code dupliqué, fonctions trop longues (>50 lignes)
   - Violations PEP 8 importantes
   - Imports non utilisés

3. **STYLE** (LOW severity): Problèmes de style mineur
   - Formatage, espaces, conventions de nommage mineures
   - Ordre des imports

4. **TESTS** (MEDIUM): Manque de tests
   - Fonctions critiques sans tests unitaires
   - Edge cases non couverts

Pour CHAQUE problème, fournis:
- severity: "HIGH" | "MEDIUM" | "LOW"
- type: "BUG" | "QUALITY" | "STYLE" | "TESTS"
- line: numéro de ligne (0 si non applicable)
- description: description claire et spécifique du problème
- suggestion: correction spécifique et actionnable pour le Fixer agent

Crée aussi une liste de priorités ordonnée pour guider le Fixer agent.

IMPORTANT: Réponds UNIQUEMENT en JSON valide (pas de markdown, pas de texte avant/après):
{{
    "file_path": "{file_path}",
    "pylint_score": {pylint_results['score']},
    "issues": [
        {{
            "severity": "HIGH",
            "type": "BUG",
            "line": 15,
            "description": "Division par zéro possible dans calculate()",
            "suggestion": "Ajouter: if denominator == 0: raise ValueError('Cannot divide by zero')"
        }}
    ],
    "refactoring_priority": [
        "Fix division by zero in calculate()",
        "Add docstrings to all functions",
        "Rename variables a, b to meaningful names"
    ],
    "estimated_fixes": 5,
    "summary": "Le fichier contient X problèmes majeurs à corriger en priorité"
}}
"""
        return prompt
    
    def _parse_llm_response(self, output: str, file_path: str, pylint_results: Dict) -> Dict:
        """Parse la réponse JSON du LLM"""
        
        json_start = output.find('{')
        json_end = output.rfind('}') + 1
        
        if json_start != -1 and json_end > json_start:
            result = json.loads(output[json_start:json_end])
            
            # Validation et valeurs par défaut
            result.setdefault('file_path', file_path)
            result.setdefault('pylint_score', pylint_results['score'])
            result.setdefault('issues', [])
            result.setdefault('refactoring_priority', [])
            result.setdefault('estimated_fixes', len(result['issues']))
            result.setdefault('summary', 'Analyse complète')
            
            return result
        else:
            raise ValueError("Réponse LLM ne contient pas de JSON valide")
    
    def _create_fallback_analysis(
        self, 
        file_path: str, 
        pylint_results: Dict, 
        syntax_check: Dict,
        error: str
    ) -> Dict:
        """Crée une analyse de secours basée uniquement sur Pylint en cas d'échec LLM"""
        
        issues = []
        
        # Ajouter erreur de syntaxe si présente
        if not syntax_check['valid']:
            issues.append({
                'severity': 'HIGH',
                'type': 'BUG',
                'line': syntax_check['line'] or 0,
                'description': f"Erreur de syntaxe: {syntax_check['error']}",
                'suggestion': 'Corriger la syntaxe Python'
            })
        
        # Convertir messages Pylint en issues
        for msg in pylint_results.get('messages', [])[:20]:
            severity = 'HIGH' if msg.get('type') == 'error' else 'MEDIUM' if msg.get('type') == 'warning' else 'LOW'
            issues.append({
                'severity': severity,
                'type': 'QUALITY',
                'line': msg.get('line', 0),
                'description': msg.get('message', 'Unknown issue'),
                'suggestion': f"Voir Pylint: {msg.get('symbol', 'N/A')}"
            })
        
        return {
            'file_path': file_path,
            'pylint_score': pylint_results['score'],
            'issues': issues,
            'refactoring_priority': ['Corriger les erreurs Pylint identifiées'],
            'estimated_fixes': len(issues),
            'summary': f"⚠️ Analyse de secours (Pylint uniquement). Erreur: {error}"
        }
    
    def _create_error_analysis(self, file_path: str, error: str) -> Dict:
        """Crée une analyse d'erreur"""
        return {
            'file_path': file_path,
            'pylint_score': 0.0,
            'issues': [{
                'severity': 'HIGH',
                'type': 'BUG',
                'line': 0,
                'description': error,
                'suggestion': 'Vérifier que le fichier existe et est lisible'
            }],
            'refactoring_priority': [],
            'estimated_fixes': 0,
            'summary': f"❌ Erreur: {error}"
        }
    
    def analyze_directory(self, directory_path: str) -> List[Dict]:
        """Analyse tous les fichiers Python d'un répertoire
        
        Args:
            directory_path: Chemin du répertoire à analyser
            
        Returns:
            list: Liste des analyses pour chaque fichier
        """
        print(f"\n{'='*60}")
        print(f"🔍 ANALYSE DU RÉPERTOIRE: {directory_path}")
        print(f"{'='*60}\n")
        
        # Récupérer tous les fichiers Python
        python_files = FileOperations.get_python_files(directory_path)
        
        if not python_files:
            print(f"⚠️ Aucun fichier Python trouvé dans {directory_path}")
            return []
        
        print(f"📂 {len(python_files)} fichier(s) Python trouvé(s)\n")
        
        results = []
        for i, file_path in enumerate(python_files, 1):
            print(f"\n[{i}/{len(python_files)}] Analyse de: {file_path}")
            print("-" * 60)
            
            try:
                content = FileOperations.read_file(file_path)
                analysis = self.analyze_file(file_path, content)
                results.append(analysis)
                
            except Exception as e:
                print(f"❌ Erreur lors de l'analyse de {file_path}: {e}")
                results.append(self._create_error_analysis(file_path, str(e)))
        
        print(f"\n{'='*60}")
        print(f"✅ ANALYSE TERMINÉE: {len(results)} fichier(s) analysé(s)")
        print(f"{'='*60}\n")
        
        return results
    
    def generate_report(self, analyses: List[Dict]) -> str:
        """Génère un rapport texte lisible des analyses
        
        Args:
            analyses: Liste des résultats d'analyse
            
        Returns:
            str: Rapport formaté
        """
        report = []
        report.append("=" * 80)
        report.append("RAPPORT D'AUDIT DE CODE")
        report.append("=" * 80)
        report.append("")
        
        total_issues = sum(len(a['issues']) for a in analyses)
        avg_score = sum(a['pylint_score'] for a in analyses) / len(analyses) if analyses else 0
        
        report.append(f"📊 Statistiques Générales:")
        report.append(f"  - Fichiers analysés: {len(analyses)}")
        report.append(f"  - Problèmes totaux: {total_issues}")
        report.append(f"  - Score Pylint moyen: {avg_score:.2f}/10")
        report.append("")
        
        for analysis in analyses:
            report.append("-" * 80)
            report.append(f"📄 {analysis['file_path']}")
            report.append(f"   Score: {analysis['pylint_score']}/10 | Problèmes: {len(analysis['issues'])}")
            report.append("")
            
            if analysis['issues']:
                report.append("   🔴 Problèmes identifiés:")
                for issue in analysis['issues'][:5]:  # Limiter à 5 par fichier
                    report.append(f"     [{issue['severity']}] L{issue['line']}: {issue['description']}")
                
                if len(analysis['issues']) > 5:
                    report.append(f"     ... et {len(analysis['issues']) - 5} autres problèmes")
            
            report.append("")
        
        report.append("=" * 80)
        
        return "\n".join(report)
