#include<bits/stdc++.h>
using namespace std;
int n,d;
double sum;
struct fish{
	long long v,k;
	double s;
}a[10005];
bool cmp(fish l,fish r){
	return l.s > r.s;
}
int main()
{
	cin >> n >> d;
	for(long long i = 1;i <= n;++ i){
		cin >> a[i].k;
	}
	for(long long i = 1;i <= n;++ i){
		cin >> a[i].v;
		a[i].s = (double)a[i].v / a[i].k;
	}
	sort(a + 1,a + n + 1,cmp);
	for(long long i = 1;i <= n;++ i){
		if(d > a[i].k){
			sum += a[i].v;
			d -= a[i].k;
		}else{
			sum += (a[i].s*d);
			break;
		}
	}
	printf("%.2lf",sum);
	return 0;
}

