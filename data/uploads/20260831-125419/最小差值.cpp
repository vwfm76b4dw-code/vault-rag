#include <bits/stdc++.h>
using namespace std;
int a[10001];
int n;
int sum=2147483647;
int main()
{
	cin>>n;
	for(int i=1;i<=n;i++){
		cin>>a[i];
	}
	for(int i=1;i<=n;i++){
		for(int j=1;j<=n;j++){
			if(abs(a[i]-a[j])<sum&&i!=j)sum=abs(a[i]-a[j]);
		}
	}
	cout<<sum;
}
