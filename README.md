# Implementation Roadmap Canon

Shared canon for AI-led implementation roadmaps.

This repository is meant to be pinned by product repositories and reused outside
one local workspace. Product repositories keep their live state locally; this
repository owns the common process.

## Layers

| Layer | Lives here? | Examples |
|---|---:|---|
| Common canon | Yes | milestone/slice lifecycle, review contract, closure rules, continuation rules, templates |
| Local state | No | roadmap, milestone index, active continuation, work logs, review logs, closures, accepted debt, mandates |

Do not put product status in this repository. Do not fork the process text into
each product unless the fork is intentionally temporary and recorded locally.

## Repository Layout

```text
canon/
  process/        # versioned common process
templates/
  local-state/    # files a product repo copies and owns
```

## Pinning From A Product Repository

Use a submodule when the product should pin an exact canon revision:

```bash
git submodule add <canon-git-url> vendor/impl_roadmap_canon
git -C vendor/impl_roadmap_canon checkout v0.8.0
git add .gitmodules vendor/impl_roadmap_canon
git commit -m "Pin implementation roadmap canon"
```

Then copy the local-state templates into the product repository:

```bash
cp -R vendor/impl_roadmap_canon/templates/local-state/implementation ./implementation
```

The copied `implementation/` tree becomes local state. It should link back to
the pinned canon, not duplicate it.

## Upgrading

Upgrade deliberately:

```bash
git -C vendor/impl_roadmap_canon fetch --tags
git -C vendor/impl_roadmap_canon checkout <new-tag-or-commit>
git add vendor/impl_roadmap_canon
git commit -m "Update implementation roadmap canon"
```

If a product must temporarily diverge, record the reason in its local
`implementation/process/README.md` and remove the divergence during the next
canon upgrade.
