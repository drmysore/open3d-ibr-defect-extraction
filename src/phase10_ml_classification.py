"""TLL-12: ML Ensemble Defect Classification.

Trains and evaluates Random Forest, XGBoost-style (Gradient Boosting),
and LightGBM-style ensemble with cost-aware loss (2000:1 FN weighting).

Since XGBoost and LightGBM may not be available in all environments,
we implement gradient-boosted equivalents using scikit-learn's
GradientBoostingClassifier with class-weight-like sample weighting.
"""

import os
import sys

# Ensure project src is on path when run from project root (e.g. run_sprint4.py)
_src_dir = os.path.dirname(os.path.abspath(__file__))
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

import numpy as np
import json
import os
import time
from typing import Optional
from sklearn.ensemble import (
    RandomForestClassifier,
    GradientBoostingClassifier,
)
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.metrics import (
    accuracy_score,
    classification_report,
    roc_auc_score,
    confusion_matrix,
)
from sklearn.preprocessing import StandardScaler
import joblib


class DefectClassifier:
    """TLL-12: Three-model ensemble with cost-aware training."""

    FN_WEIGHT = 2000

    def __init__(self, model_dir: str = "models"):
        self.model_dir = model_dir
        os.makedirs(model_dir, exist_ok=True)

        self.scaler = StandardScaler()

        self.rf = RandomForestClassifier(
            n_estimators=500,
            max_depth=15,
            class_weight={0: 1, 1: self.FN_WEIGHT},
            n_jobs=-1,
            random_state=42,
        )

        self.gb1 = GradientBoostingClassifier(
            n_estimators=300,
            max_depth=8,
            learning_rate=0.05,
            subsample=0.8,
            random_state=42,
        )

        self.gb2 = GradientBoostingClassifier(
            n_estimators=300,
            max_depth=8,
            learning_rate=0.05,
            subsample=0.7,
            max_features="sqrt",
            random_state=123,
        )

        self.is_trained = False
        self.training_metrics: dict = {}

    def train(
        self,
        features: np.ndarray,
        labels: np.ndarray,
        feature_names: Optional[list[str]] = None,
    ) -> dict:
        """Train all three models with cost-aware sample weighting."""
        t0 = time.time()
        n_samples, n_features = features.shape
        print(f"  [TLL-12] Training on {n_samples} samples x {n_features} features")

        X = self.scaler.fit_transform(features)
        y = labels.astype(int)

        sample_weights = np.ones(n_samples)
        non_serviceable = y == 0
        sample_weights[non_serviceable] = self.FN_WEIGHT

        print(f"  [TLL-12] Class distribution: serviceable={int(np.sum(y == 1))}, "
              f"non-serviceable={int(np.sum(y == 0))}")

        print("  [TLL-12] Training Random Forest (500 trees)...")
        self.rf.fit(X, y)

        print("  [TLL-12] Training Gradient Boosting Model 1 (XGB-style)...")
        self.gb1.fit(X, y, sample_weight=sample_weights)

        print("  [TLL-12] Training Gradient Boosting Model 2 (LGB-style)...")
        self.gb2.fit(X, y, sample_weight=sample_weights)

        self.is_trained = True

        metrics = self._evaluate(X, y, sample_weights, feature_names)
        metrics["training_time_s"] = round(time.time() - t0, 2)
        self.training_metrics = metrics

        self._save_models()

        print(f"  [TLL-12] Training complete in {metrics['training_time_s']}s")
        print(f"  [TLL-12] Ensemble accuracy: {metrics['ensemble']['accuracy']:.4f}")
        print(f"  [TLL-12] Ensemble AUC-ROC:  {metrics['ensemble']['auc_roc']:.4f}")
        print(f"  [TLL-12] False Negative Rate: {metrics['ensemble']['false_negative_rate']:.4f}")

        return metrics

    def predict(self, features: np.ndarray) -> dict:
        """Ensemble prediction with confidence scores."""
        if not self.is_trained:
            self._load_models()

        X = self.scaler.transform(features)
        n = len(X)

        prob_rf = self.rf.predict_proba(X)[:, 1]
        prob_gb1 = self.gb1.predict_proba(X)[:, 1]
        prob_gb2 = self.gb2.predict_proba(X)[:, 1]

        prob_ensemble = (prob_rf + prob_gb1 + prob_gb2) / 3.0
        predictions = (prob_ensemble > 0.5).astype(int)
        confidence = np.maximum(prob_ensemble, 1.0 - prob_ensemble)

        model_agreement = np.zeros(n)
        preds_all = np.column_stack([
            (prob_rf > 0.5).astype(int),
            (prob_gb1 > 0.5).astype(int),
            (prob_gb2 > 0.5).astype(int),
        ])
        for i in range(n):
            model_agreement[i] = np.mean(preds_all[i] == predictions[i])

        return {
            "predictions": predictions,
            "probabilities": prob_ensemble,
            "confidence": confidence,
            "model_agreement": model_agreement,
            "individual_probs": {
                "random_forest": prob_rf,
                "gradient_boost_1": prob_gb1,
                "gradient_boost_2": prob_gb2,
            },
        }

    def predict_defect_types(self, features: np.ndarray, defects: list[dict]) -> list[dict]:
        """Classify defect types using geometric heuristics + ML confidence."""
        result = self.predict(features)

        type_names = ["nick", "dent", "crack", "FOD", "erosion", "scratch", "gouge"]

        for i, defect in enumerate(defects):
            depth = defect.get("depth_mm", 0.0)
            length = defect.get("length_mm", 0.0)
            width = defect.get("width_mm", 0.0)
            aspect = length / max(width, 1e-6)
            is_edge = defect.get("classification") == "edge"

            if is_edge and aspect > 3.0:
                dtype = "scratch"
            elif is_edge and depth > 0.1:
                dtype = "nick"
            elif aspect > 5.0 and depth < 0.05:
                dtype = "scratch"
            elif aspect > 2.5:
                dtype = "gouge"
            elif depth > 0.2 and length < 0.5:
                dtype = "dent"
            elif depth > 0.3:
                dtype = "FOD"
            elif width > length * 0.8 and depth < 0.1:
                dtype = "erosion"
            else:
                dtype = "nick"

            defect["classified_type"] = dtype
            defect["ml_serviceable_prob"] = float(result["probabilities"][i])
            defect["ml_confidence"] = float(result["confidence"][i])
            defect["ml_prediction"] = "SERVICEABLE" if result["predictions"][i] == 1 else "NON_SERVICEABLE"
            defect["ml_model_agreement"] = float(result["model_agreement"][i])

        return defects

    def _evaluate(
        self,
        X: np.ndarray,
        y: np.ndarray,
        sample_weights: np.ndarray,
        feature_names: Optional[list[str]],
    ) -> dict:
        metrics = {}

        for name, model in [("random_forest", self.rf), ("gb_model_1", self.gb1), ("gb_model_2", self.gb2)]:
            pred = model.predict(X)
            prob = model.predict_proba(X)[:, 1]

            cm = confusion_matrix(y, pred, labels=[0, 1])
            tn, fp, fn, tp = cm.ravel() if cm.size == 4 else (0, 0, 0, len(y))

            metrics[name] = {
                "accuracy": float(accuracy_score(y, pred)),
                "auc_roc": float(roc_auc_score(y, prob)) if len(np.unique(y)) > 1 else 1.0,
                "false_negative_rate": float(fn / max(fn + tp, 1)),
                "confusion_matrix": cm.tolist(),
            }

        prob_ensemble = (
            self.rf.predict_proba(X)[:, 1]
            + self.gb1.predict_proba(X)[:, 1]
            + self.gb2.predict_proba(X)[:, 1]
        ) / 3.0
        pred_ensemble = (prob_ensemble > 0.5).astype(int)

        cm = confusion_matrix(y, pred_ensemble, labels=[0, 1])
        tn, fp, fn, tp = cm.ravel() if cm.size == 4 else (0, 0, 0, len(y))

        metrics["ensemble"] = {
            "accuracy": float(accuracy_score(y, pred_ensemble)),
            "auc_roc": float(roc_auc_score(y, prob_ensemble)) if len(np.unique(y)) > 1 else 1.0,
            "false_negative_rate": float(fn / max(fn + tp, 1)),
            "confusion_matrix": cm.tolist(),
        }

        if feature_names and hasattr(self.rf, "feature_importances_"):
            importances = self.rf.feature_importances_
            top_idx = np.argsort(importances)[::-1][:10]
            metrics["top_features"] = [
                {"name": feature_names[i], "importance": float(importances[i])}
                for i in top_idx
            ]

        return metrics

    def _save_models(self):
        joblib.dump(self.rf, os.path.join(self.model_dir, "rf_model.joblib"))
        joblib.dump(self.gb1, os.path.join(self.model_dir, "gb1_model.joblib"))
        joblib.dump(self.gb2, os.path.join(self.model_dir, "gb2_model.joblib"))
        joblib.dump(self.scaler, os.path.join(self.model_dir, "scaler.joblib"))

        with open(os.path.join(self.model_dir, "training_metrics.json"), "w") as f:
            json.dump(self.training_metrics, f, indent=2, default=str)

        print(f"  [TLL-12] Models saved to {self.model_dir}/")

    def _load_models(self):
        try:
            self.rf = joblib.load(os.path.join(self.model_dir, "rf_model.joblib"))
            self.gb1 = joblib.load(os.path.join(self.model_dir, "gb1_model.joblib"))
            self.gb2 = joblib.load(os.path.join(self.model_dir, "gb2_model.joblib"))
            self.scaler = joblib.load(os.path.join(self.model_dir, "scaler.joblib"))
            self.is_trained = True
            print("  [TLL-12] Models loaded from disk")
        except FileNotFoundError:
            raise RuntimeError("No trained models found. Run train() first.")


def generate_training_data(defects: list[dict], augment_factor: int = 50) -> tuple[np.ndarray, np.ndarray]:
    """Generate augmented training data from pipeline defects.

    Applies realistic perturbations to create 1000+ samples from a small
    set of detected defects, as specified in TLL-12 data requirements.
    """
    n_base = len(defects)
    if n_base == 0:
        return np.zeros((0, 58)), np.zeros(0)

    from phase9_feature_extraction import FeatureExtractor
    extractor = FeatureExtractor()
    base_features, _ = extractor.extract_all(defects)

    base_labels = np.array([
        1.0 if d.get("disposition") == "SERVICEABLE" else 0.0
        for d in defects
    ])

    all_features = [base_features]
    all_labels = [base_labels]

    rng = np.random.RandomState(42)
    for _ in range(augment_factor):
        noise = rng.normal(0, 0.05, base_features.shape)
        augmented = base_features + noise * np.abs(base_features + 1e-8)
        augmented = np.clip(augmented, 0, None)

        flip_mask = rng.random(len(base_labels)) < 0.05
        aug_labels = base_labels.copy()
        aug_labels[flip_mask] = 1 - aug_labels[flip_mask]

        all_features.append(augmented)
        all_labels.append(aug_labels)

    synthetic_serviceable = rng.normal(0, 0.3, (200, 58))
    synthetic_serviceable[:, 0] = rng.uniform(0.001, 0.05, 200)
    synthetic_serviceable[:, 1] = rng.uniform(0.1, 1.0, 200)
    synthetic_serviceable[:, 2] = rng.uniform(0.1, 0.5, 200)
    synthetic_serviceable[:, 57] = 1.0
    all_features.append(synthetic_serviceable)
    all_labels.append(np.ones(200))

    synthetic_replace = rng.normal(0, 0.3, (200, 58))
    synthetic_replace[:, 0] = rng.uniform(0.2, 1.0, 200)
    synthetic_replace[:, 1] = rng.uniform(2.0, 10.0, 200)
    synthetic_replace[:, 2] = rng.uniform(1.0, 5.0, 200)
    synthetic_replace[:, 57] = 0.0
    all_features.append(synthetic_replace)
    all_labels.append(np.zeros(200))

    X = np.vstack(all_features)
    y = np.concatenate(all_labels)

    X = np.nan_to_num(X, nan=0.0)

    print(f"  [TLL-12] Generated {len(X)} training samples "
          f"(base={n_base}, augmented={n_base * augment_factor}, synthetic=400)")
    return X, y
