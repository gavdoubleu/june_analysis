# Release sync (dev-only)

`dev` is the working branch (tests, ADRs, plans, CONTEXT.md, this dir). `release`
is what users clone from GitHub — main code + user docs only, squash-committed
per version.

## Cutting a release

```
git checkout dev
git pull
dev-only/sync_to_release.sh v1.2.0
git show release --stat   # sanity check
git push origin release dev v1.2.0
```

The script wipes `release`'s tree, repopulates it from dev's current tree minus
the excluded paths, squash-commits, and tags the release commit `v1.2.0`
(message records the source dev commit SHA — git tags can't point at two
commits, so `dev`'s commit for this version is only identified via that SHA,
not a matching tag).

## Excluded from release

- `**/tests/**`
- `docs/adr/`
- `docs/plans/`
- `CONTEXT.md`
- `dev-only/` (this directory)

Edit `EXCLUDES` in `sync_to_release.sh` to change the list.

## One-time setup (already done)

- `master` renamed to `dev`.
- `release` branch created off `dev`, first sync run.
- GitHub default branch should be set to `release` once it exists on origin,
  so a plain clone gets the clean tree.
