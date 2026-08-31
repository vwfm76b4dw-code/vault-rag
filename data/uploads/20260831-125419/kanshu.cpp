#include <bits/stdc++.h>
#define ll long long 
using namespace std;
const int N=1e6;
ll n,m,ans;
ll h[N];
bool check(ll x){//判断传过来的答案是否合法 
	ll sum=0;
	for(int i=1;i<=n;i++){
		if(h[i]>=x)
		sum+=h[i]-x;
	}
	return sum>=m;
}
int main(){
cin>>n>>m;
ll l=0,r=0,mid=0; //初始化 
//第一步，先确定答案的合法区间【l,r】 
for(int i=1;i<=n;i++) {
	cin>>h[i];
	r=max(r,h[i]);
}
//二分法，寻找唯一答案 
while(l<=r) {
	mid=(l+r)>>1;
	if(check(mid)){
		ans=mid;
		l=mid+1;//如果低于mid的值都是满足答案的 
	}
	else
	r=mid-1; 
}
cout<<ans<<endl;
return 0;
}

