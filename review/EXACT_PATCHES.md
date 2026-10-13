# Exact correction review — https://pontotocnews.com

Read-only authenticated preflight. No WordPress writes or media uploads performed.

Any later apply must re-read and compare the full before snapshot, including revision. Stop on a mismatch or 403. Preserve all unlisted fields. Account capability eligibility is not proof of a successful write.

{"capabilities": {"edit_others_posts": true, "edit_posts": true, "edit_published_posts": true, "upload_files": true}, "id": 2}

## Post 5955

https://pontotocnews.com/pontotoc-news/ummc-lactation-team-supports-new-mothers-in-breastfeeding-journey/

- Before snapshot SHA-256: `eef632e445a02787756f5804c11668abfc0ce42f8a7033c760274cb6e22f8cc5`
- Payload SHA-256: `4c085f030f3189c9baf06413250e6f9f9c2c84216c354fc4db6492a5b47f585c`
- Owned by account: True

### content

```diff
--- before
+++ proposed
@@ -1,3 +1,3 @@
-<p>The University of Maryland Medical Center offers extensive support to new mothers through its lactation team, helping women initiate and maintain breastfeeding.</p> <p>UMMC has held the designation of a Baby-Friendly Hospital since 2017, signifying its commitment to supporting mothers and babies during the breastfeeding process.</p> <p>Additional resources and information about the benefits of breastfeeding are available on UMMC's website.</p>
+<p>The University of Mississippi Medical Center offers extensive support to new mothers through its lactation team, helping women initiate and maintain breastfeeding.</p> <p>UMMC has held the designation of a Baby-Friendly Hospital since 2017, signifying its commitment to supporting mothers and babies during the breastfeeding process.</p> <p>Additional resources and information about the benefits of breastfeeding are available on UMMC's website.</p>
 
 <p><em>Source: <a href="https://www.facebook.com/1291582679669685/posts/1534410632053554" target="_blank" rel="noopener">Original Article</a></em></p>
```

### excerpt

```diff
--- before
+++ proposed
@@ -1 +1 @@
-The University of Maryland Medical Center's lactation team provides education and support to new moms, reinforcing its commitment as a Baby-Friendly Hospital since 2017.+The University of Mississippi Medical Center's lactation team provides education and support to new moms, reinforcing its commitment as a Baby-Friendly Hospital since 2017.
```

### Sources

- https://www.facebook.com/1291582679669685/posts/1534410632053554

## Later application boundary

Use the payload digest to bind approved JSON and the before-snapshot digest to detect concurrent edits. The proposed-snapshot hash is a planning fingerprint, not the expected live rendered response: WordPress rendering must be verified separately after any approved write. No apply route exists on this review branch. After approved verified application, retire any one-shot mutation route created for it.
