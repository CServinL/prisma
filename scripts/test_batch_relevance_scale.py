"""Stress test: batch relevance check with hundreds of Zotero-like items (title + abstract)."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from prisma.agents.analysis_agent import AnalysisAgent

QUERY = "super resolution image reconstruction"

# (title, abstract, ground_truth)
ITEMS: list[tuple[str, str | None, bool]] = [
    # --- RELEVANT ---
    ("Real-ESRGAN: Training Real-World Blind Super-Resolution with Pure Synthetic Data",
     "We propose Real-ESRGAN, a practical blind super-resolution algorithm trained with a high-order degradation process. Our method can restore real-world degraded images with complex unknown degradations.",
     True),
    ("SRCNN: Image Super-Resolution Using Deep Convolutional Networks",
     "We propose a deep convolutional neural network for single image super-resolution. The network directly learns an end-to-end mapping between low- and high-resolution images.",
     True),
    ("Blind Image Super-Resolution via Contrastive Representation Learning",
     "We present a blind super-resolution method that handles unknown and complex degradations. Contrastive learning is used to learn degradation-invariant representations for upscaling.",
     True),
    ("Perceptual Losses for Real-Time Style Transfer and Super-Resolution",
     "We train feed-forward networks for style transfer and super-resolution using perceptual loss functions based on high-level features extracted from pretrained CNNs.",
     True),
    ("Neural Network Approaches to Single Image Super-Resolution: A Survey",
     "This survey covers deep learning methods for single image super-resolution, including CNN-based, GAN-based, and attention-based approaches for upscaling low-resolution images.",
     True),
    ("Photo-Realistic Single Image Super-Resolution Using a Generative Adversarial Network",
     "We present SRGAN, a generative adversarial network for 4x upscaling factors. We propose a perceptual loss function to recover photo-realistic textures from heavily downsampled images.",
     True),
    ("Enhanced Deep Residual Networks for Single Image Super-Resolution",
     "We propose EDSR, a residual network architecture for image super-resolution that achieves state-of-the-art performance by removing batch normalization and using residual scaling.",
     True),
    ("Deep Recursive Residual Network for Super Resolution",
     "We propose a deeply recursive residual network (DRRN) for single image super-resolution that uses recursive learning and residual learning to achieve high-quality upscaling.",
     True),
    ("Accurate Image Super-Resolution Using Very Deep Convolutional Networks",
     "We present VDSR, a highly accurate single-image super-resolution method using very deep convolutional networks inspired by VGG. The network jointly trains for multiple scale factors.",
     True),
    ("Deep Laplacian Pyramid Networks for Fast and Accurate Super-Resolution",
     "We develop LapSRN, a deep Laplacian pyramid network for fast and accurate super-resolution of images. The model progressively reconstructs high-resolution images at multiple scales.",
     True),
    ("Residual Dense Network for Image Super-Resolution",
     "We propose the Residual Dense Network (RDN) to address single image super-resolution. We fully exploit hierarchical features from original low-resolution images via dense connected residual blocks.",
     True),
    ("SwinIR: Image Restoration Using Swin Transformer",
     "We propose SwinIR for image restoration tasks including image super-resolution, denoising, and JPEG compression artifact reduction. It uses a Swin Transformer backbone with residual groups.",
     True),
    ("Efficient Sub-Pixel Convolutional Neural Network for Image Super-Resolution",
     "We introduce an efficient sub-pixel convolutional layer that aggregates feature maps from low-resolution space and computes high-resolution output in real time for image super-resolution.",
     True),
    ("Deep Back-Projection Networks for Super-Resolution",
     "We propose back-projection networks for super-resolution that use iterative up- and down-sampling layers and error feedback to compute high-resolution images from low-resolution inputs.",
     True),
    ("Channel Attention Image Restoration",
     "We propose a channel attention mechanism for image restoration tasks, including super-resolution, denoising, and compression artifact reduction, achieving state-of-the-art performance.",
     True),
    ("Unpaired Image-to-Image Translation for Super-Resolution",
     "We apply unpaired image-to-image translation using cycle-consistent adversarial networks to learn super-resolution mappings without paired low- and high-resolution training examples.",
     True),
    ("Burst Photography for High Dynamic Range and Low-Light Imaging on Mobile Cameras",
     "We present a computational pipeline for burst photography that merges multiple frames to achieve super-resolution, HDR, and noise reduction on mobile camera hardware.",
     True),
    ("Image Denoising Using a Generative Adversarial Network",
     "We propose a GAN-based approach for blind image denoising that recovers clean images from noisy inputs, serving as a preprocessing step for downstream super-resolution pipelines.",
     True),
    ("Non-Local Recurrent Network for Image Restoration",
     "We present NLRN, a non-local recurrent network for image restoration. Non-local operations capture long-range dependencies to improve super-resolution and denoising accuracy.",
     True),
    ("Image Deblurring with Blurred/Noisy Image Pairs",
     "We propose a deep learning approach that jointly uses blurred and noisy image pairs for image deblurring and restoration, producing sharper high-quality reconstructions.",
     True),
    ("BasicVSR: The Search for Essential Components in Video Super-Resolution",
     "We present BasicVSR, a minimal framework for video super-resolution that systematically explores essential components including optical flow, residuals, and recurrent propagation.",
     True),
    ("TDAN: Temporally-Deformable Alignment Network for Video Super-Resolution",
     "We propose a temporally-deformable alignment network that adaptively aligns video frames at the feature level for video super-resolution without explicit motion compensation.",
     True),
    ("Second-Order Attention Network for Single Image Super-Resolution",
     "We propose a second-order channel attention mechanism for single image super-resolution that captures feature correlations more effectively than first-order statistics-based methods.",
     True),
    ("Image Super-Resolution via Sparse Representation",
     "We present an image super-resolution method via sparse representation of patches. High-resolution patches are synthesized by enforcing sparsity in a dictionary learned from training pairs.",
     True),
    ("Image Restoration Using Convolutional Auto-encoders with Symmetric Skip Connections",
     "We propose RED-Net, a convolutional autoencoder with symmetric skip connections for image restoration including denoising and super-resolution. Skip connections allow clean signal propagation.",
     True),
    ("Multi-Scale Residual Network for Image Super-Resolution",
     "We propose MSRN, a multi-scale residual network that adaptively detects image features at multiple scales to reconstruct high-resolution images from low-resolution inputs.",
     True),
    ("Generative Adversarial Networks for Image Super Resolution: A Survey",
     "This paper surveys GAN-based super-resolution methods, covering loss functions, network architectures, and training strategies for upscaling images with perceptual quality.",
     True),
    ("Feedback Network for Image Super-Resolution",
     "We introduce SRFBN, a feedback network for image super-resolution. High-level information is fed back to low-level layers to refine early features for better reconstruction.",
     True),
    ("Lightweight Image Super-Resolution with Information Multi-distillation Network",
     "We propose IMDN, a lightweight super-resolution network using information multi-distillation blocks that progressively distill features for efficient high-resolution image reconstruction.",
     True),
    ("Anchored Neighborhood Regression for Fast Example-Based Super-Resolution",
     "We propose ANR, an anchored neighborhood regression approach for example-based super-resolution. Dictionary atoms anchor local regression models for fast high-resolution image synthesis.",
     True),
    # --- NOT RELEVANT ---
    ("Attention is All You Need",
     "We propose the Transformer, a model architecture relying entirely on an attention mechanism to draw global dependencies between input and output for machine translation tasks.",
     False),
    ("Grassmannian quantum cohomology in the infinite limit and total positivity",
     "We study the quantum cohomology rings of Grassmannians in the infinite limit and establish connections with total positivity theory and the Edrei theorem on Toeplitz matrices.",
     False),
    ("T-Rex: Tactile-Reactive Dexterous Manipulation",
     "We propose T-Rex, a framework for tactile-reactive dexterous robotic manipulation using a variable-rate mixture-of-transformers architecture with a temporal tactile VQ-VAE encoder.",
     False),
    ("Consensus-based Agentic LLM Framework for Harmonized Tariff Schedule Classification",
     "We propose a multi-agent LLM framework for HTS code classification in maritime logistics, integrating semantic retrieval, consensus validation, and human-in-the-loop escalation.",
     False),
    ("BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding",
     "We introduce BERT, a new language representation model which pre-trains deep bidirectional transformers from unlabeled text for a wide range of NLP tasks.",
     False),
    ("AlphaFold: A Solution to a 50-Year-Old Grand Challenge in Biology",
     "We present AlphaFold, a deep learning system that predicts protein 3D structures with atomic accuracy from amino acid sequences, solving a decades-old challenge in biology.",
     False),
    ("Reinforcement Learning from Human Feedback for Code Generation",
     "We fine-tune large language models for code generation using reinforcement learning from human feedback, significantly improving correctness on programming benchmarks.",
     False),
    ("CLIP: Learning Transferable Visual Models from Natural Language Supervision",
     "We present CLIP, which learns visual concepts from natural language supervision. CLIP is trained on image-text pairs and achieves strong zero-shot transfer to many visual tasks.",
     False),
    ("YOLOv8: Real-Time Object Detection",
     "We present YOLOv8, a state-of-the-art real-time object detection model that achieves competitive accuracy while maintaining fast inference speed for autonomous and industrial applications.",
     False),
    ("Neural Radiance Fields for View Synthesis",
     "We present NeRF, a method to synthesize novel views of complex scenes by optimizing an underlying continuous volumetric scene function using a sparse set of input images.",
     False),
    ("3D Gaussian Splatting for Real-Time Novel View Synthesis",
     "We introduce 3D Gaussian Splatting, which represents scenes as 3D Gaussians for real-time novel view synthesis, achieving high visual quality with fast training and rendering.",
     False),
    ("Medical Image Segmentation with U-Net",
     "We present U-Net, a convolutional network for biomedical image segmentation. The architecture consists of a contracting path and an expanding path with skip connections.",
     False),
    ("SAM: Segment Anything Model",
     "We introduce SAM, a promptable model for zero-shot image segmentation trained on 1 billion masks. SAM generalizes to new image distributions and tasks without fine-tuning.",
     False),
    ("Drug Discovery with Graph Neural Networks",
     "We apply graph neural networks to molecular property prediction and drug discovery, representing molecules as graphs to predict binding affinity and toxicity.",
     False),
    ("Federated Learning: Challenges, Methods, and Future Directions",
     "We survey federated learning, a training paradigm where models are trained across decentralized devices without sharing raw data, covering privacy, communication, and heterogeneity challenges.",
     False),
    ("Knowledge Distillation: A Survey",
     "We present a comprehensive survey of knowledge distillation, covering teacher-student training, feature-based, response-based, and relation-based distillation methods.",
     False),
    ("Autonomous Driving with End-to-End Deep Learning",
     "We train an end-to-end deep learning system for autonomous driving that maps raw camera input directly to steering and throttle commands using imitation learning.",
     False),
    ("Graph Neural Networks: A Review of Methods and Applications",
     "We review graph neural networks covering spectral and spatial convolutions, pooling methods, and applications in social networks, chemistry, and knowledge graphs.",
     False),
    ("Time Series Forecasting with Temporal Convolutional Networks",
     "We show that temporal convolutional networks outperform recurrent architectures on a wide range of time series forecasting and sequence modeling benchmarks.",
     False),
    ("Stable Diffusion: High-Resolution Image Synthesis with Latent Diffusion Models",
     "We present latent diffusion models that apply diffusion in a compressed latent space to generate high-resolution images efficiently with text conditioning.",
     False),
    ("Scaling Laws for Neural Language Models",
     "We study empirical scaling laws for language model performance on the cross-entropy loss. Loss scales as a power law with model size, dataset size, and compute.",
     False),
    ("FlashAttention: Fast and Memory-Efficient Exact Attention with IO-Awareness",
     "We present FlashAttention, an IO-aware exact attention algorithm that uses tiling to reduce memory reads and writes, achieving 2-4x faster training with lower memory footprint.",
     False),
    ("Parameter-Efficient Fine-Tuning with LoRA",
     "We propose LoRA, which freezes pretrained model weights and injects trainable rank decomposition matrices into each layer, drastically reducing trainable parameters for fine-tuning.",
     False),
    ("Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks",
     "We combine parametric memory in a seq2seq model with non-parametric memory in a dense vector index for open-domain question answering and knowledge-intensive generation.",
     False),
    ("Chain-of-Thought Prompting Elicits Reasoning in Large Language Models",
     "We show that generating a chain of thought — a series of intermediate reasoning steps — significantly improves the ability of large language models to perform complex reasoning.",
     False),
    ("Zero-Shot Learning via Class Attribute Vectors",
     "We propose zero-shot learning by mapping visual features to semantic attribute vectors, enabling recognition of unseen classes without any training examples.",
     False),
    ("Multi-Task Learning for NLP with Shared Representations",
     "We present a multi-task learning framework for natural language processing that shares lower-layer representations across tasks while maintaining task-specific output layers.",
     False),
    ("Bounds for Genus Zero Gromov-Witten Invariants",
     "We give bounds for the norm of each primary genus zero Gromov-Witten invariant using Siebert's formula and the D-volume intermediate count of curves.",
     False),
    ("Speech Recognition with Deep Recurrent Neural Networks",
     "We present deep recurrent neural networks for end-to-end speech recognition, using CTC loss to train directly from audio spectrograms to character sequences.",
     False),
    ("Anomaly Detection in Industrial Images via Reconstruction",
     "We detect anomalies in industrial inspection images by training an autoencoder on normal samples. Defects are identified as high reconstruction error regions at test time.",
     False),
]

relevant_count = sum(1 for *_, r in ITEMS if r)
irrelevant_count = sum(1 for *_, r in ITEMS if not r)
print(f"Topic: {QUERY!r}")
print(f"Total items: {len(ITEMS)} ({relevant_count} relevant, {irrelevant_count} not relevant)")
print("Sending in one LLM call (title + abstract)...\n")

agent = AnalysisAgent()
candidates = [(str(i), title, abstract) for i, (title, abstract, _) in enumerate(ITEMS)]
flags = agent.batch_relevance_check(QUERY, candidates)

tp = fp = tn = fn = 0
false_positives = []
false_negatives = []

for (title, abstract, ground_truth), predicted in zip(ITEMS, flags):
    if ground_truth and predicted:
        tp += 1
    elif not ground_truth and predicted:
        fp += 1
        false_positives.append(title)
    elif ground_truth and not predicted:
        fn += 1
        false_negatives.append(title)
    else:
        tn += 1

precision = tp / (tp + fp) if (tp + fp) > 0 else 0
recall = tp / (tp + fn) if (tp + fn) > 0 else 0
f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

print(f"Results:  TP={tp}  FP={fp}  TN={tn}  FN={fn}")
print(f"Precision: {precision:.2f}  Recall: {recall:.2f}  F1: {f1:.2f}")

if false_positives:
    print(f"\nFalse positives ({len(false_positives)}):")
    for t in false_positives:
        print(f"  - {t}")

if false_negatives:
    print(f"\nFalse negatives ({len(false_negatives)}):")
    for t in false_negatives:
        print(f"  - {t}")
