#include <bits/stdc++.h> 
using namespace std;
int sum=0,sum2=1;
int n;
int a[100001];
int main()
{
	cin>>n;
	for(int i=1;i<=n;i++){
		cin>>a[i];
	}
	for(int i=2;i<=n;i++){
		if(a[i]>a[i-1])sum2++;
		else {
			if(sum<sum2){
				sum=sum2;
				sum2=1;
			}
		}
	}
	cout<<sum;
}
