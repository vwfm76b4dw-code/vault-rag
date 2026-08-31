#include <bits/stdc++.h>
#define int long long
using namespace std;       
const int N = 1e5 + 5;
int a[N];                       
int sum[N*4],lazy[N*4];

void pushup(int p) {           
    sum[p] = sum[p<<1] + sum[p<<1|1];
}

void build(int p, int l, int r) {
    if (l == r) {
        sum[p]=a[l];         
        return;
    }
    int m = (l + r) >> 1;
    build(p << 1, l, m);
    build(p << 1 | 1, m + 1, r);
    pushup(p);
}
//单点修改 
void update(int p, int l, int r, int pos, int val) {  // val 为 ll
    if (l == r) {
        sum[p]+=val;         // 累加
        return;
    }
    int m = (l + r) >> 1;
    if (pos <= m) update(p << 1, l, m, pos, val);
    else update(p << 1 | 1, m + 1, r, pos, val);
    pushup(p);
}
//pushdown的目的是将懒标记传给子节点
void pushdown(int p,int l,int r) {
	if(lazy[p]==0) return;
	int mid=(l+r)>>1;
	//左子节点 
	lazy[p<<1]+=lazy[p];
	sum[p<<1]+=lazy[p]*(mid-l+1);
	// 右子节点 
	lazy[p<<1|1]+=lazy[p];
	sum[p<<1|1]+=lazy[p]*(r-mid);
	lazy[p]=0; 
}
//区间修改，将【L，R】 范围内的每个数加上d 
 void update1(int p,int l,int r,int L,int R,int d){
 	if(L<=l&&r<=R){
 		sum[p]+=(r-l+1)*d;
 		lazy[p]+=d;// lazy[p]是指p的所有子树也应该都加上d，但是先不加，寄存着 
 		return;
	 }
	 pushdown(p,l,r);// lazy[p]的下放 
	 //递归更新子节点、
	 int mid=(l+r)>>1;
	 if(L<=mid) update1(p<<1,l,mid,L,R,d);
	 if(R>mid)  update1(p<<1|1,mid+1,r,L,R,d);
	 pushup(p);
 	
 }
int query(int p, int l, int r, int ql, int qr) {      // 返回 ll
    if (ql <= l && r <= qr) return sum[p];
    pushdown(p,l,r);
    int m = (l + r) >> 1;
    int res = 0;
    if (ql <= m) res += query(p << 1, l, m, ql, qr);
    if (qr>m) res += query(p << 1 | 1, m + 1, r, ql, qr);
    return res;
}

signed main() {
    ios::sync_with_stdio(false);
    cin.tie(0);
    int n, m;
    cin >> n >> m;
 for(int i=1;i<=n;i++) cin>>a[i];
    build(1, 1, n);
    while (m--) {
        int op,x, y,k;
        cin >> op ;
        if (op == 1) {
        	cin>>x>>y>>k;
            update1(1, 1, n, x, y,k);
        } else {  
            cin>>x>>y;
            cout<<query(1, 1, n, x, y) << '\n';
        }
    }
    return 0;
}
