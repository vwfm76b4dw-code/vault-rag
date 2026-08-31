#include <bits/stdc++.h>
using namespace std;
long long int a[100001];
int main()
{
	long long int n;
	cin>>n;
	a[1]=1;
	a[2]=1;
	for(long long int i=3;i<=n;i++){
		a[i]=a[i-1]+a[i-2];
		cout<<"µЪ"<<i<<"По:"<<a[i]<<endl; 
	}
}
