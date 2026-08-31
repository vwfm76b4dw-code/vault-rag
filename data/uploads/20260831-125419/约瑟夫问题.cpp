#include <bits/stdc++.h>
using namespace std;
int a[1000000];
int n,m,c;
int main()
{
	cin>>n>>m;
	for(int i=1;i<=n;i++)a[i]=i;
	int sum=0,i=1;
	while(sum<n){
		if(i>n)i=1;
		if(a[i]!=0)c++;
		if(c==m){
			cout<<a[i]<<" ";
			a[i]=0;
			c=0;
			sum++;
		}
		i++;
	}
}
