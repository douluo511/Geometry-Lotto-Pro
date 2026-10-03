# Happy8 isolated seed validation

This file exists only to trigger pull_request validation against the isolated Happy8 seed branch.

Validation invariant:
- product/runtime tree under `Happy8/staging` must remain byte-identical to source exact head `64dfe1b9274abecd972edaa52c928f10cb2b6b23`;
- no other portfolio project files are present in the seed tree;
- this file is not part of the runtime, build input, updater payload, or release artifact;
- successful validation does not satisfy E17/E18/E19 by itself because the repository is still the shared GitHub repository.
