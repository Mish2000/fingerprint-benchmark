# Stage 8A acquisition manifests

This directory records what was actually available for the three candidates
frozen before qualification.  It contains metadata and hashes only.  It does
not contain model weights, third-party source, biometric images, embeddings, or
scores.

Each JSON file is a strict, fingerprinted `CandidateArtifactManifest`.  A
present component names its exact immutable source, byte size and SHA-256 where
bytes were acquired.  A required component that could not be acquired remains
an explicit `present: false` entry; a paper or mutable URL is never promoted to
inference code or a checkpoint.

The AFR-Net and MGViT manifests contain the content identities of their
official papers because no official or author-supplied executable artifact was
acquired.  The `flx` manifest separately identifies:

- author repository commit `7accfca1f33b9b42bfd220e43cd5bc13b4a7fa13`;
- its source archive and inspected inference files;
- `best_model.pyt`, including its exact size, SHA-256, detected variant and
  branch dimensions;
- the unpinned dependency list;
- source, weights and third-party licence conclusions.

The checkpoint is not committed to this repository.  Its manifest locator is
an acquisition reference, not permission for runtime download: qualification
must use an explicitly supplied local artifact root, and the offline verifier
rehashes every required file before use.  These commit-3 manifests make no
qualification or selection conclusion; those are derived in later evidence.
