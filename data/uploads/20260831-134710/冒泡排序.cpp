#include <bits/stdc++.h>
int a[100005],n; 
using namespace std;
int main()
{
	cin>>n;
	for(int i=0;i<n;i++){
		cin>>a[i];
	}
	for(int i=0;i<n;i++){
		for(int j=0;j<n-i;j++){
			if(a[j]>a[j+1])swap(a[j],a[j+1]);
		}
	}
	for(int i=0;i<n;i++){
		cout<<a[i]<<ends;
	}
	return 0;
}

