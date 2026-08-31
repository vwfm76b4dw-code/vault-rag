#include <bits/stdc++.h>
using namespace std;
int a[1000001];
int n,m;
int sum;
int main()
{
	cin>>n>>m;
	for(int i=1;i<=n;i++){
		cin>>a[i];
	}
	for(int i=1;i<n;i++){
		for(int j=1+i;j<=n;j++){
			if((a[i]+a[j])%m==0)sum++;
		}
	}
	cout<<sum;
}
