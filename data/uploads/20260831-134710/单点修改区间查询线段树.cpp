#include <bits/stdc++.h>
using namespace std;
long long a[4000005];
long long sum[4000005];
long long n,m;
void pushup(long long p) {
    sum[p] = sum[p << 1] + sum[p << 1 | 1];
}
void build(long long p, long long l, long long r) {
    if (l == r) {
        sum[p] = a[l];
        return;
    }
    long long mid = (l + r) >> 1;
    build(p << 1, l, mid);
    build(p << 1 | 1, mid + 1, r);
    pushup(p);
}
void update(long long p, long long l, long long r, long long pos, long long val) {
    if (l == r) {
        sum[p] = val;
        return;
    }
    long long mid = (l + r) >> 1;
    if (pos <= mid) update(p << 1, l, mid, pos, val);
    else update(p << 1 | 1, mid + 1, r, pos, val);
    pushup(p);
}
long long query(long long p, long long l, long long r, long long ql, long long qr) {
    if (ql <= l && r <= qr) return sum[p];
    long long mid = (l + r) >> 1;
    long long ans = 0;
    if (ql <= mid) ans += query(p << 1, l, mid, ql, qr);
    if (qr > mid) ans += query(p << 1 | 1, mid + 1, r, ql, qr);
    return ans;
}
int main() {
    ios::sync_with_stdio(false);
    cin.tie(0);
    cout.tie(0);
    cin >> n >> m;
    for (long long i = 1; i <= n; i++){
		cin >> a[i];    	
	} 
    build(1,1,n);
  	for(long long i = 1;i <= m;++ i){
  		long long op,x,y;
  		cin >> op >> x >> y; 
	  	if(op == 2){
	  		update(1,1,n,x,y);
		} else {
		  	cout << query(1,1,n,x,y) << endl;
		}
    }
    return 0;
}
