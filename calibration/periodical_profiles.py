"""Periodical frequency profiles from the node table of periodical_tree.py.

Titles are classed by median issues per volume; per class it prints page share,
volumes per title, issues per volume, and the pages-per-issue hierarchy
(sigma between titles / within title), supplements and articles.

    uv run --with numpy calibration/periodical_profiles.py TREE.npz
"""
import sys

import numpy as np

z=np.load(sys.argv[1]); M=list(z['models']); t,d,m,par,pg,ch=(z[k] for k in 'title depth model parent pages children'.split())

T=t.max()+1
vol=M.index('periodicalvolume'); it=M.index('periodicalitem'); sup=M.index('supplement')
isv=(m==vol); isi=(m==it)&(par>=0)
isi_under_v = isi & (m[np.maximum(par,0)]==vol)
nv=np.bincount(t[isv],minlength=T)
# items per volume = count items whose parent is volume
ipv=np.bincount(par[isi_under_v], minlength=len(t))[isv]
vt=t[isv]
def med(vals,groups):
    o=np.full(T,np.nan); order=np.argsort(groups,kind='stable'); g=groups[order]; v=vals[order]
    b=np.flatnonzero(np.diff(g))+1
    for gg,vv in zip(np.split(g,b),np.split(v,b), strict=False): o[gg[0]]=np.median(vv)
    return o
mi=med(ipv,vt)
ppi_rows=isi&(pg>0); mp=med(pg[ppi_rows],t[ppi_rows])

T=t.max()+1
vol,it,sup,art=(M.index(x) for x in ['periodicalvolume','periodicalitem','supplement','article'])
pmodel=np.where(par>=0,m[np.maximum(par,0)],-1)
edges=[1,2,4,6,10,16,31,61,251,1e9]; names=['annual','2-3/yr','quarterly','bimonthly','monthly','biweekly','weekly','several/wk','daily']
cls=np.full(T,-1); ok=~np.isnan(mi); cls[ok]=np.digitize(mi[ok],edges)-1
subtree=np.bincount(t,weights=pg,minlength=T)
isi=(m==it)&(pmodel==vol); isv=m==vol
ipv=np.bincount(par[isi],minlength=len(t))
print(f"{'profile':12} {'titles':>6} {'pages%':>6} {'vol med/p90':>11} {'ipv med [p10-p90]':>18} {'ppi title-med med':>17} {'σ_between':>9} {'σ_within':>8} {'sup/vol':>7} {'sup/item':>8} {'art/item':>8} {'ppsup med':>9} {'even%':>5} {'m4%':>4}")
tot=pg.sum()
for c,nm in enumerate(names):
    tt=np.flatnonzero(cls==c); S=np.isin(t,tt)
    vmask=isv&S; imask=isi&S&(pg>0)
    v=nv[tt]; ipvv=ipv[vmask]
    lp=np.log(pg[imask]); tm=np.log(mp[t[imask]])
    sb=np.std(np.log(mp[tt])); sw=np.std(lp-tm)
    supv=np.sum((m==sup)&(pmodel==vol)&S)/max(vmask.sum(),1)
    items=np.sum(isi&S)
    supi=np.sum((m==sup)&(pmodel==it)&S)/max(items,1)
    arti=np.sum((m==art)&(pmodel==it)&S)/max(items,1)
    pps=pg[(m==sup)&S&(pg>0)]
    x=pg[imask]
    print(f"{nm:12} {len(tt):6d} {100*subtree[tt].sum()/tot:6.1f} {np.median(v):5.0f}/{np.percentile(v,90):<5.0f} {np.median(ipvv):6.0f} [{np.percentile(ipvv,10):.0f}-{np.percentile(ipvv,90):.0f}]{'':4} {np.median(mp[tt]):17.0f} {sb:9.2f} {sw:8.2f} {supv:7.2f} {supi:8.3f} {arti:8.3f} {np.median(pps) if pps.size else 0:9.0f} {100*np.mean(x%2==0):5.0f} {100*np.mean(x%4==0):4.0f}")
# within-title: ipv dispersion relative to title median, per class
print()
for c,nm in enumerate(names):
    tt=np.flatnonzero(cls==c); S=np.isin(t,tt); vmask=isv&S
    r=ipv[vmask]/mi[t[vmask]]
    print(f"{nm:12} ipv/title_median quantiles p5,p25,p50,p75,p95:", np.round(np.percentile(r,[5,25,50,75,95]),2), " frac==median:", round(float(np.mean(ipv[vmask]==np.round(mi[t[vmask]]))),2))
# volume count vs class correlation, and nv distribution per class shape
print("\nvolumes per title by profile (p25,p50,p75,p90,max):")
for c,nm in enumerate(names):
    v=nv[cls==c]; print(f"  {nm:12}", np.percentile(v,[25,50,75,90]).round(0), v.max())
