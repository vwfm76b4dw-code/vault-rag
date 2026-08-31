#include<bits/stdc++.h>
using namespace std;
int a[1000],n,sum;
int main()
{
	cin>>n;
	for(int i=1;i<=n;i++)cin>>a[i];
	for(int i=2;i<n;i++){
		if(a[i-1]>a[i]){
			for(int j=i+1;true;j++){
				if(a[j]>a[j-1]){
					sum++;
					break;
				}
				if(a[j]<a[j-1])break;
			}
		}
	}
	cout<<sum;
}
