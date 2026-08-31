#include <bits/stdc++.h>
using namespace std;
int a[10001];
int n; 
int sum;
int main()
{
	cin>>n;
	for(int i=1;i<=n;i++){
		cin>>a[i];
	}
	for(int i=1;i<=n;i++){
		if(a[i-1]>a[i]&&a[i+1]<a[i])sum++;
	}
	cout<<sum;
    return 0;
}

