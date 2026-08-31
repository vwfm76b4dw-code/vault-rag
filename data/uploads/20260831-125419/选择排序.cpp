#include <bits/stdc++.h>
using namespace std;
double a[105];
int temp;
int main()
{
	int n;
	cin>>n;
	for(int i=1;i<=n;i++){
		cin>>a[i];
	 }
	for(int i=1;i<n;i++){
		int temp=i;
		for(int j=i+1;j<=n;j++){
			if(a[temp]>a[j]){
				temp=j;
			}
		}
		swap(a[i],a[temp]);
	}
	for(int i=1;i<=n;i++){
		cout<<a[i]<<ends;
	}
	return 0;
}

